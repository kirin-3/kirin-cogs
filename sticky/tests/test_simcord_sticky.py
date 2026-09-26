"""Sticky on a real Red instance driven through SimCord.

Every flow runs over the real gateway events: commands as messages, the
repost triggered by ``MESSAGE_CREATE``, the repost triggered when the sticky
itself is deleted (``MESSAGE_DELETE``), and the repost cooldown elapsing on
the virtual clock (``advance_time`` composes with ``red_env``'s pinned
``utcnow``). ``channel.history()`` only lists live messages, so "exactly one
live copy, with a new id" doubles as the no-duplicates assertion throughout.

The interactive ``[p]unsticky`` confirmation parks the bot on a 30-second
``wait_for`` while holding the channel's repost lock, and SimCord's ``settle``
refuses to outwait that park. Those two tests inject the command message and
the deciding reaction straight through the backend, let a short ``settle``
time out on purpose (by then the prompt is posted and the ``wait_for`` is
registered) and only then deliver the reaction.
"""

import contextlib
from dataclasses import dataclass
from typing import Any, cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from sticky.sticky import HEADER, Sticky

YES = "\N{WHITE HEAVY CHECK MARK}"
NO = "\N{NEGATIVE SQUARED CROSS MARK}"


@pytest.fixture
def red_cogs() -> list[str]:
    return ["sticky"]


@dataclass
class Setup:
    bot: Red
    cog: Sticky
    guild: simcord.GuildHandle
    owner: simcord.MemberActor
    member: simcord.MemberActor
    channel: simcord.ChannelHandle


async def _setup(env: simcord.Env) -> Setup:
    bot = cast(Red, env.bot)
    owner_user = env.create_user("owner")
    guild = env.create_guild("Unicornia", owner=owner_user)
    owner = guild.add_member(owner_user)
    member = guild.add_member(env.create_user("member"))
    channel = guild.create_text_channel("general")
    await env.settle()
    cog = bot.get_cog("Sticky")
    assert isinstance(cog, Sticky)
    return Setup(bot, cog, guild, owner, member, channel)


def _bot_messages(setup: Setup) -> list[discord.Message]:
    bot_user = setup.bot.user
    assert bot_user is not None
    return [m for m in setup.channel.history() if m.author.id == bot_user.id]


def _live_with(setup: Setup, text: str) -> list[discord.Message]:
    return [m for m in _bot_messages(setup) if text in m.content]


def _live_ids(setup: Setup) -> set[int]:
    return {m.id for m in setup.channel.history()}


async def _settings(setup: Setup) -> dict[str, Any]:
    return await setup.cog.conf.channel_from_id(setup.channel.id).all()


async def _sticky(env: simcord.Env, setup: Setup, content: str) -> discord.Message:
    """Run ``[p]sticky`` and return the one live sticky message it posted."""
    await setup.owner.send(setup.channel, f"!sticky {content}")
    await env.settle()
    live = _live_with(setup, content)
    assert len(live) == 1
    return live[0]


async def _begin_confirmation(env: simcord.Env, setup: Setup) -> discord.Message:
    """Drive ``[p]unsticky`` up to its parked confirmation and return the prompt."""
    env.backend.create_message(setup.channel.id, setup.owner.id, "!unsticky")
    with contextlib.suppress(TimeoutError):
        await env.settle(timeout=0.3)
    prompts = [m for m in _bot_messages(setup) if "Are you sure" in m.content]
    assert prompts, "the unsticky confirmation prompt was never posted"
    return prompts[-1]


@pytest.mark.asyncio
async def test_sticky_posts_immediately_and_replaces_the_old_copy(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    first = await _sticky(red_env, setup, "First version")
    assert first.content == f"{HEADER}\n\nFirst version"
    settings = await _settings(setup)
    assert settings["stickied"] == "First version"
    assert settings["last"] == first.id

    second = await _sticky(red_env, setup, "Second version")
    assert second.id != first.id
    assert first.id not in _live_ids(setup)  # the replaced copy was deleted
    settings = await _settings(setup)
    assert settings["stickied"] == "Second version"
    assert settings["last"] == second.id

    # The delete event for the replaced copy must not resurrect a duplicate.
    await red_env.advance_time(5)
    await red_env.settle()
    assert len(_live_with(setup, "Second version")) == 1
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_new_message_reposts_the_sticky_and_deletes_the_old_copy(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    original = await _sticky(red_env, setup, "Read the rules")

    await setup.member.send(setup.channel, "hello!")
    # The 3-second default cooldown is short enough that settle simply waits it
    # out in real time; advance_time covers it either way.
    await red_env.advance_time(4)
    await red_env.settle()

    reposted = _live_with(setup, "Read the rules")
    assert len(reposted) == 1 and reposted[0].id != original.id
    assert original.id not in _live_ids(setup)
    assert any(m.content == "hello!" for m in setup.channel.history())  # only the sticky was deleted
    assert (await _settings(setup))["last"] == reposted[0].id
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_the_bot_never_reposts_to_its_own_sticky(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    original = await _sticky(red_env, setup, "Read the rules")

    await red_env.advance_time(6)
    await red_env.settle()
    await red_env.advance_time(6)
    await red_env.settle()

    assert [m.id for m in _live_with(setup, "Read the rules")] == [original.id]
    assert (await _settings(setup))["last"] == original.id
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_deleting_the_sticky_reposts_it(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    original = await _sticky(red_env, setup, "Read the rules")

    await setup.owner.delete(original)
    await red_env.advance_time(4)
    await red_env.settle()

    reposted = _live_with(setup, "Read the rules")
    assert len(reposted) == 1 and reposted[0].id != original.id
    assert (await _settings(setup))["last"] == reposted[0].id
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_deleting_an_ordinary_message_is_ignored(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    chatter = await setup.member.send(setup.channel, "just chatting")
    await red_env.settle()
    original = await _sticky(red_env, setup, "Read the rules")

    await setup.owner.delete(chatter)
    await red_env.settle()
    await red_env.advance_time(4)
    await red_env.settle()

    assert [m.id for m in _live_with(setup, "Read the rules")] == [original.id]
    assert (await _settings(setup))["last"] == original.id
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_unsticky_yes_clears_the_sticky_and_keeps_channel_settings(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await _sticky(red_env, setup, "Keep me")
    await setup.owner.send(setup.channel, "!sticky toggleheader false")
    await setup.owner.send(setup.channel, "!sticky cooldown 30")
    await red_env.settle()
    sticky = _live_with(setup, "Keep me")[0]

    await setup.owner.send(setup.channel, "!unsticky yes")
    await red_env.settle()

    settings = await _settings(setup)
    assert settings["stickied"] is None
    assert settings["advstickied"] == {"content": None, "embed": {}}
    assert settings["last"] is None
    assert settings["header_enabled"] is False  # channel settings survive
    assert settings["cooldown"] == 30
    assert sticky.id not in _live_ids(setup)

    # The delete of the sticky itself (inside unsticky) must not repost it.
    await setup.member.send(setup.channel, "hello!")
    await red_env.advance_time(35)
    await red_env.settle()
    assert not _live_with(setup, "Keep me")

    await setup.owner.send(setup.channel, "!unsticky yes")
    await red_env.settle()
    assert any("There is no stickied message in this channel." in m.content for m in _bot_messages(setup))
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_unsticky_confirmation_accepts_the_checkmark(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    sticky = await _sticky(red_env, setup, "Keep me")

    prompt = await _begin_confirmation(red_env, setup)
    assert {str(r.emoji) for r in prompt.reactions} >= {YES, NO}
    red_env.backend.add_reaction(setup.channel.id, prompt.id, YES, setup.owner.id)
    await red_env.settle()

    settings = await _settings(setup)
    assert settings["last"] is None and settings["stickied"] is None
    assert sticky.id not in _live_ids(setup)
    assert prompt.id in _live_ids(setup)  # the prompt stays after a confirmed unsticky

    await red_env.advance_time(5)
    await red_env.settle()
    assert not _live_with(setup, "Keep me")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_unsticky_declined_keeps_the_sticky(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await _sticky(red_env, setup, "Keep me")

    prompt = await _begin_confirmation(red_env, setup)
    red_env.backend.add_reaction(setup.channel.id, prompt.id, NO, setup.owner.id)
    await red_env.settle()

    assert prompt.id not in _live_ids(setup)  # a declined prompt is cleaned up
    settings = await _settings(setup)
    assert settings["stickied"] == "Keep me"

    # The sticky stays active: it still follows the conversation below the prompt.
    await red_env.advance_time(5)
    await red_env.settle()
    live = _live_with(setup, "Keep me")
    assert len(live) == 1
    assert (await _settings(setup))["last"] == live[0].id
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_sticky_existing_copies_content_and_first_embed(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    source = red_env.backend.create_message(
        setup.channel.id,
        setup.member.id,
        "Existing content",
        embeds=[{"title": "Existing embed", "description": "from the source"}],
    )
    await red_env.settle()

    await setup.owner.send(setup.channel, f"!sticky existing {source.id}")
    await red_env.settle()

    live = _live_with(setup, "Existing content")
    assert len(live) == 1
    assert live[0].content == f"{HEADER}\n\nExisting content"
    assert live[0].embeds and live[0].embeds[0].title == "Existing embed"
    settings = await _settings(setup)
    assert settings["stickied"] is None
    assert settings["advstickied"]["content"] == "Existing content"
    assert settings["advstickied"]["embed"]["title"] == "Existing embed"

    # The embed survives the repost path too.
    await setup.member.send(setup.channel, "hello!")
    await red_env.advance_time(4)
    await red_env.settle()
    reposted = _live_with(setup, "Existing content")
    assert len(reposted) == 1 and reposted[0].embeds and reposted[0].embeds[0].title == "Existing embed"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_cooldown_bounds_and_reset(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.owner.send(setup.channel, "!sticky cooldown 1")
    await red_env.settle()
    assert any("cannot be set lower than **3 seconds**" in m.content for m in _bot_messages(setup))
    assert (await _settings(setup))["cooldown"] == 3

    await setup.owner.send(setup.channel, "!sticky cooldown 30")
    await red_env.settle()
    assert (await _settings(setup))["cooldown"] == 30

    await setup.owner.send(setup.channel, "!sticky cooldown")
    await red_env.settle()
    assert any("reset to the default (**3 seconds**)" in m.content for m in _bot_messages(setup))
    assert (await _settings(setup))["cooldown"] == 3
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_a_longer_cooldown_delays_the_repost(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    original = await _sticky(red_env, setup, "Read the rules")
    await setup.owner.send(setup.channel, "!sticky cooldown 10")
    await red_env.settle()

    await setup.member.send(setup.channel, "hello!")
    await red_env.advance_time(4)
    await red_env.settle()
    assert [m.id for m in _live_with(setup, "Read the rules")] == [original.id]  # still within the cooldown

    await red_env.advance_time(10)
    await red_env.settle()
    reposted = _live_with(setup, "Read the rules")
    assert len(reposted) == 1 and reposted[0].id != original.id
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_toggleheader_removes_the_header_from_reposts(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await _sticky(red_env, setup, "Read the rules")
    await setup.owner.send(setup.channel, "!sticky toggleheader false")
    await red_env.settle()

    await setup.member.send(setup.channel, "hi")
    await red_env.advance_time(4)
    await red_env.settle()

    reposted = _live_with(setup, "Read the rules")
    assert len(reposted) == 1 and reposted[0].content == "Read the rules"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_commands_need_mod_or_manage_messages(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.member.send(setup.channel, "!sticky nope")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    await setup.member.send(setup.channel, "!unsticky yes")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    await red_env.settle()

    # A Discord Manage Messages role satisfies the check without Red mod roles.
    mod_role = setup.guild.create_role("Mod", permissions=discord.Permissions(manage_messages=True))
    red_env.backend.add_member_role(setup.guild.id, setup.member.id, mod_role.id)
    await red_env.settle()
    await setup.member.send(setup.channel, "!sticky Mod sticky")
    await red_env.settle()
    assert len(_live_with(setup, "Mod sticky")) == 1
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_channel_without_a_sticky_stays_silent(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.member.send(setup.channel, "anybody there?")
    await red_env.settle()
    await red_env.advance_time(5)
    await red_env.settle()

    assert _bot_messages(setup) == []
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_commands_are_rejected_in_dms(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.owner.send_dm("!sticky dm attempt")
    await red_env.settle()

    dm_contents = [
        m.content
        for c in red_env.backend.channels.values()
        if setup.owner.id in c.recipient_ids
        for m in red_env.backend.messages[c.id].values()
    ]
    assert "That command is not available in DMs." in dm_contents
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)  # NoPrivateMessage
    simcord.assert_no_errors(red_env)
