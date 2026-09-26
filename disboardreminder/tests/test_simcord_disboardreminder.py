"""DisboardReminder on a real Red instance driven through SimCord.

Disboard's replies reach the cog the way they do in production: messages authored
by the real Disboard bot, recognised by the bump image on its success embed. The
actor API cannot produce them (IDs are snowflaked and send() carries no embeds),
so the Disboard bot is registered on the backend under its hardcoded ID and its
messages are injected through ``backend.create_message``, interaction metadata
included — the same omnipotent-setup idiom as the audit-log injection in the
AntiNuke suite. The two-hour reminder is fast-forwarded with ``advance_time``;
``red_env`` pins ``discord.utils.utcnow`` to the virtual clock, so the cog's
``tasks.loop`` genuinely sees the cooldown elapse.
"""

import datetime
from dataclasses import dataclass
from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red
from simcord.backend.errors import BackendError
from simcord.backend.models.message import Message
from simcord.backend.models.user import User
from simcord.backend.serializers import user_payload

from disboardreminder.disboardreminder import BUMP_COOLDOWN, DISBOARD_BOT_ID, DisboardReminder

SUCCESS_EMBED: dict = {"image": {"url": "https://disboard.org/images/bot-command-image-bump.png"}}
DEFAULT_REMINDER = "It's been 2 hours since the last successful bump"


@pytest.fixture
def red_cogs() -> list[str]:
    return ["disboardreminder"]


@dataclass
class Setup:
    bot: Red
    cog: DisboardReminder
    guild: simcord.GuildHandle
    owner: simcord.MemberActor
    member: simcord.MemberActor
    bumper: simcord.MemberActor
    channel: simcord.ChannelHandle


async def _setup(env: simcord.Env, *, configure: bool = True) -> Setup:
    bot = cast(Red, env.bot)
    owner_user = env.create_user("owner")
    guild = env.create_guild("Unicornia", owner=owner_user)
    owner = guild.add_member(owner_user)
    member = guild.add_member(env.create_user("member"))
    bumper = guild.add_member(env.create_user("bumper"))
    channel = guild.create_text_channel("bump")
    # The real Disboard bot as a member, under the ID the cog gates on.
    env.backend.users[DISBOARD_BOT_ID] = User(id=DISBOARD_BOT_ID, name="DISBOARD", bot=True)
    env.backend.add_member(guild.id, DISBOARD_BOT_ID, announce=True)
    await env.settle()

    if configure:
        await owner.send(channel, f"!bprm channel {channel.mention}")
        await env.settle()
    cog = cast(Red, env.bot).get_cog("DisboardReminder")
    assert isinstance(cog, DisboardReminder)
    return Setup(bot, cog, guild, owner, member, bumper, channel)


def _bump(
    env: simcord.Env, channel: simcord.ChannelHandle, bumper: simcord.MemberActor, *, success: bool = True
) -> Message:
    """Disboard replies in the bump channel, naming who ran /bump."""
    return env.backend.create_message(
        channel.id,
        DISBOARD_BOT_ID,
        "Bump done" if success else "Please wait 2 hours between bumps",
        embeds=[SUCCESS_EMBED] if success else None,
        interaction_metadata={
            "id": str(env.backend.snowflake()),
            "type": 2,
            "user": user_payload(env.backend.users[bumper.id]),
        },
    )


def _bot_replies(handle: simcord.ChannelHandle, bot: Red) -> list[discord.Message]:
    bot_user = bot.user
    assert bot_user is not None
    return [m for m in handle.history() if m.author.id == bot_user.id]


async def _config(setup: Setup) -> dict:
    return await setup.cog.config.guild_from_id(setup.guild.id).all()


@pytest.mark.asyncio
async def test_channel_command_configures_the_cog_and_settings_show_it(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    assert any(
        "Set this channel as the reminder channel for bumps." in m.content
        for m in _bot_replies(setup.channel, setup.bot)
    )
    assert (await _config(setup))["channel"] == setup.channel.id

    await setup.owner.send(setup.channel, "!bprm settings")
    await red_env.settle()
    embeds = [
        e for m in _bot_replies(setup.channel, setup.bot) for e in m.embeds if e.title == "Bump Reminder Settings"
    ]
    assert len(embeds) == 1
    description = embeds[0].description or ""
    assert f"**Channel:** {setup.channel.mention}" in description
    assert "**Ping Role:** None" in description
    assert "**Auto-lock:** False" in description
    assert embeds[0].footer.text is None  # no bump registered yet
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_commands_need_manage_server(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.member.send(setup.channel, "!bprm settings")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_successful_bump_is_thanked_and_schedules_the_reminder(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    message = _bump(red_env, setup.channel, setup.bumper)
    await red_env.settle()

    assert any(
        m.content.startswith(f"{setup.bumper.mention} thank you for bumping!")
        and f"https://disboard.org/server/{setup.guild.id}" in m.content
        for m in _bot_replies(setup.channel, setup.bot)
    )
    bump_time = datetime.datetime.fromisoformat(message.timestamp).timestamp()
    assert (await _config(setup))["nextBump"] == pytest.approx(bump_time + BUMP_COOLDOWN)

    await setup.owner.send(setup.channel, "!bprm settings")
    await red_env.settle()
    settings = [e for m in _bot_replies(setup.channel, setup.bot) for e in m.embeds][-1]
    assert settings.footer.text == "Next bump registered for"
    assert settings.timestamp is not None
    assert abs(settings.timestamp.timestamp() - (bump_time + BUMP_COOLDOWN)) < 1
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_second_bump_within_the_cooldown_changes_nothing(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    first = _bump(red_env, setup.channel, setup.bumper)
    await red_env.settle()
    _bump(red_env, setup.channel, setup.bumper)
    await red_env.settle()

    thanks = [m for m in _bot_replies(setup.channel, setup.bot) if "thank you for bumping" in m.content]
    assert len(thanks) == 1
    first_time = datetime.datetime.fromisoformat(first.timestamp).timestamp()
    assert (await _config(setup))["nextBump"] == pytest.approx(first_time + BUMP_COOLDOWN)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_reminder_arrives_two_hours_later_and_only_once(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    _bump(red_env, setup.channel, setup.bumper)
    await red_env.settle()
    await red_env.advance_time(BUMP_COOLDOWN + 60)
    await red_env.settle()

    reminders = [m for m in _bot_replies(setup.channel, setup.bot) if m.content.startswith(DEFAULT_REMINDER)]
    assert len(reminders) == 1
    assert (await _config(setup))["nextBump"] is None

    # The cleared nextBump keeps later loop ticks from repeating the reminder.
    await red_env.advance_time(120)
    assert len([m for m in _bot_replies(setup.channel, setup.bot) if m.content.startswith(DEFAULT_REMINDER)]) == 1
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_clearing_the_channel_silences_a_due_reminder(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    _bump(red_env, setup.channel, setup.bumper)
    await red_env.settle()
    await setup.owner.send(setup.channel, "!bprm channel")
    await red_env.settle()
    assert any("Disabled bump reminders in this server." in m.content for m in _bot_replies(setup.channel, setup.bot))

    await red_env.advance_time(BUMP_COOLDOWN + 60)
    await red_env.settle()
    assert not [m for m in _bot_replies(setup.channel, setup.bot) if m.content.startswith(DEFAULT_REMINDER)]
    assert (await _config(setup))["nextBump"] is None  # still consumed, so it cannot pile up
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_custom_messages_render_placeholders(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.owner.send(setup.channel, "!bprm ty Thanks {member(name)}, nice one!")
    await setup.owner.send(setup.channel, "!bprm message Bump {server} (id {server(id)}) pls")
    await red_env.settle()
    _bump(red_env, setup.channel, setup.bumper)
    await red_env.settle()

    assert any(m.content == "Thanks bumper, nice one!" for m in _bot_replies(setup.channel, setup.bot))

    await red_env.advance_time(BUMP_COOLDOWN + 60)
    await red_env.settle()
    assert any(m.content == f"Bump Unicornia (id {setup.guild.id}) pls" for m in _bot_replies(setup.channel, setup.bot))
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_pingrole_prefixes_the_reminder(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    pinged = setup.guild.create_role("BumpPing")
    await red_env.settle()

    await setup.owner.send(setup.channel, f"!bprm pingrole {pinged.mention}")
    await red_env.settle()
    assert any(
        f"Set {pinged.name} to ping for bump reminders." in m.content for m in _bot_replies(setup.channel, setup.bot)
    )

    _bump(red_env, setup.channel, setup.bumper)
    await red_env.settle()
    await red_env.advance_time(BUMP_COOLDOWN + 60)
    await red_env.settle()

    assert any(
        m.content.startswith(f"{pinged.mention}: {DEFAULT_REMINDER}") for m in _bot_replies(setup.channel, setup.bot)
    )
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_auto_lock_holds_the_channel_until_the_reminder_unlocks(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.owner.send(setup.channel, "!bprm lock true")
    await red_env.settle()
    _bump(red_env, setup.channel, setup.bumper)
    await red_env.settle()

    def _send_overwrite(target: discord.Member | discord.Role) -> bool | None:
        cached = setup.bot.get_channel(setup.channel.id)
        assert isinstance(cached, discord.TextChannel)
        return cached.overwrites_for(target).send_messages

    me = setup.guild.me
    assert me is not None
    everyone = me.guild.default_role
    assert _send_overwrite(everyone) is False  # locked for @everyone
    assert _send_overwrite(me) is True  # the bot kept its own send permission
    with pytest.raises(BackendError):
        await setup.bumper.send(setup.channel, "locked out")

    await red_env.advance_time(BUMP_COOLDOWN + 60)
    await red_env.settle()
    assert any(m.content.startswith(DEFAULT_REMINDER) for m in _bot_replies(setup.channel, setup.bot))
    assert _send_overwrite(everyone) is None  # unlocked
    await setup.bumper.send(setup.channel, "unlocked again")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_clean_deletes_disboard_failures_but_keeps_successes(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.owner.send(setup.channel, "!bprm clean true")
    await red_env.settle()
    _bump(red_env, setup.channel, setup.bumper)
    failure = _bump(red_env, setup.channel, setup.bumper, success=False)
    await red_env.settle()
    await red_env.advance_time(3)
    await red_env.settle()

    remaining = {m.id: m.content for m in setup.channel.history()}
    assert failure.id not in remaining  # the failed-bump reply was cleaned up
    assert any(content == "Bump done" for content in remaining.values())  # the success stays
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_bump_without_a_channel_configured_is_ignored(red_env: simcord.Env) -> None:
    setup = await _setup(red_env, configure=False)

    _bump(red_env, setup.channel, setup.bumper)
    await red_env.settle()

    assert not [m for m in _bot_replies(setup.channel, setup.bot) if "thank you for bumping" in m.content]
    assert (await _config(setup))["nextBump"] is None
    simcord.assert_no_errors(red_env)
