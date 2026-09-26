"""Roleplay on a real Red instance driven through SimCord.

Covers the Discord-facing half of the cog: the dynamically registered action
commands, the consent question's Yes/No buttons, and the settings commands the
consent decisions are driven by. The consent decision table itself is pure
logic and already covered by test_roleplay_decide.py.
"""

from typing import cast

import discord
import pytest
import simcord
from redbot.core.bot import Red

from roleplay import const
from roleplay.main import Roleplay


@pytest.fixture
def red_cogs() -> list[str]:
    return ["roleplay"]


def _cog(env: simcord.Env) -> Roleplay:
    cog = cast(Red, env.bot).get_cog("Roleplay")
    assert isinstance(cog, Roleplay)
    return cog


def _bot_messages(channel: simcord.ChannelHandle, bot: Red) -> list[discord.Message]:
    assert bot.user is not None
    return [m for m in channel.history() if m.author.id == bot.user.id]


def _member(actor: simcord.MemberActor) -> discord.Member:
    """The actor's discord.py member, the way the cog sees it."""
    member = actor.member
    assert member is not None
    return member


def _me(env: simcord.Env, guild: simcord.GuildHandle) -> discord.Member:
    """The bot's own member in the guild, the way the cog sees it."""
    bot_guild = cast(Red, env.bot).get_guild(guild.id)
    assert bot_guild is not None
    member = bot_guild.me
    assert member is not None
    return member


async def _ask_action(
    channel: simcord.ChannelHandle,
    bot: Red,
    actor: simcord.MemberActor,
    action: str,
    target: simcord.MemberActor,
) -> discord.Message:
    """Run an action command and return the consent question it asks."""
    await actor.send(channel, f"!{action} {_member(target).mention}")
    return _find_message(channel, bot, "Do you consent?")


def _find_message(channel: simcord.ChannelHandle, bot: Red, text: str) -> discord.Message:
    return next(m for m in _bot_messages(channel, bot) if text in (m.content or ""))


def _assert_buttons_disabled(channel: simcord.ChannelHandle, bot: Red, text: str) -> None:
    """Re-read the message from the backend, then check every button is disabled."""
    message = _find_message(channel, bot, text)
    items = [item for row in message.components for item in getattr(row, "children", [])]
    assert items, "expected the question's buttons to still be there"
    assert all(getattr(item, "disabled", False) for item in items)


@pytest.mark.asyncio
async def test_roleplay_help_lists_the_actions(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!roleplay")

    embed = _bot_messages(channel, bot)[-1].embeds[0]
    assert embed.title == "Roleplay Commands"
    actions_field = next(f for f in embed.fields if f.name == "Actions")
    assert "**!hug**: Hug a user." in (actions_field.value or "")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_action_without_target_is_performed_by_the_bot(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    # With no target the requester is the target, so nobody is asked anything.
    await member.send(channel, "!hug")

    messages = _bot_messages(channel, bot)
    assert len(messages) == 1
    embed = messages[0].embeds[0]
    description = embed.description or ""
    assert _me(red_env, guild).mention in description
    assert _member(member).mention in description
    assert embed.image is not None
    image_url = embed.image.url
    assert image_url is not None
    assert image_url.startswith("https://")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_action_proceeds_after_the_target_accepts(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    question = await _ask_action(channel, bot, hugger, "hug", target)

    assert _member(target).mention in question.content
    assert "**hugger**" in question.content

    await target.click(question, label="Yes")

    action = next(m for m in _bot_messages(channel, bot) if m.embeds)
    description = action.embeds[0].description or ""
    assert _member(hugger).mention in description
    assert _member(target).mention in description
    _assert_buttons_disabled(channel, bot, "Do you consent?")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_action_is_refused_when_the_target_declines(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    question = await _ask_action(channel, bot, hugger, "hug", target)

    await target.click(question, label="No")

    refusal = _bot_messages(channel, bot)[-1]
    assert "**target** does not wish to do that." in refusal.content
    assert not any(m.embeds for m in _bot_messages(channel, bot))
    _assert_buttons_disabled(channel, bot, "Do you consent?")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_only_the_asked_member_can_answer_the_question(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    bystander = guild.add_member(red_env.create_user("bystander"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    question = await _ask_action(channel, bot, hugger, "hug", target)

    turned_away = await bystander.click(question, label="Yes")
    assert turned_away.response is not None
    assert turned_away.response.content == "This question isn't for you."
    assert turned_away.response.ephemeral

    # The question is still open: the target's own Yes completes the action.
    await target.click(question, label="Yes")
    assert any(m.embeds for m in _bot_messages(channel, bot))
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_unanswered_consent_times_out(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await _ask_action(channel, bot, hugger, "hug", target)
    await red_env.advance_time(const.TIMEOUT + 1)

    timed_out = _bot_messages(channel, bot)[-1]
    assert "**target** took too long to respond." in timed_out.content
    assert not any(m.embeds for m in _bot_messages(channel, bot))
    _assert_buttons_disabled(channel, bot, "Do you consent?")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_blocked_members_cannot_be_actioned_at_all(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = _cog(red_env)
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await target.send(channel, f"!roleplay settings blocked add {_member(hugger).mention}")
    assert "hugger has been added as a Blocked Users for target." in (_bot_messages(channel, bot)[-1].content or "")
    assert await cog.user_settings.config.user(_member(target)).blocked() == [hugger.id]

    # Blocked short-circuits everything: no consent question, no action message.
    await hugger.send(channel, f"!hug {_member(target).mention}")

    denied = _bot_messages(channel, bot)[-1]
    assert "you can't use that command on" in denied.content
    assert not any("Do you consent?" in (m.content or "") for m in _bot_messages(channel, bot))
    assert not any(m.embeds for m in _bot_messages(channel, bot))
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_public_consent_setting_skips_the_question(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = _cog(red_env)
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await target.send(channel, "!roleplay settings public true")
    assert "target is now a Public Use Slut." in (_bot_messages(channel, bot)[-1].content or "")
    assert await cog.user_settings.config.user(_member(target)).public() is True

    await hugger.send(channel, f"!hug {_member(target).mention}")

    action = _bot_messages(channel, bot)[-1]
    assert action.embeds
    assert _member(hugger).mention in (action.embeds[0].description or "")
    assert not any("Do you consent?" in (m.content or "") for m in _bot_messages(channel, bot))
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_ask_passes_the_action_to_the_target(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    requester = guild.add_member(red_env.create_user("requester"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await requester.send(channel, f"!ask hug {_member(target).mention}")
    question = _find_message(channel, bot, "Do you consent?")
    assert "**requester** wants you to hug them" in question.content

    await target.click(question, label="Yes")

    # Passive tense swaps the parties: the target is the one hugging.
    action = next(m for m in _bot_messages(channel, bot) if m.embeds)
    description = action.embeds[0].description or ""
    assert description.index(_member(target).mention) < description.index(_member(requester).mention)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_settings_button_shows_the_settings_embed(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!roleplay settings")
    prompt = _find_message(channel, bot, "Click the button to view your Roleplay settings.")

    shown = await member.click(prompt, label="Show Settings")

    assert shown.response is not None
    assert shown.response.ephemeral
    assert shown.response.embeds[0].title == "Roleplay Settings (member):"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_settings_cannot_be_read_for_others_without_admin(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    other = guild.add_member(red_env.create_user("other"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, f"!roleplay settings {_member(other).mention}")

    # can_manage() refuses and says so; the settings prompt never appears.
    denied = _bot_messages(channel, bot)[-1]
    assert "is not allowed to use this command on" in denied.content
    assert not any("Click the button" in (m.content or "") for m in _bot_messages(channel, bot))
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_toggle_set_for_the_member_site_shows_in_settings(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    cog = _cog(red_env)

    await cog.set_toggle(member.id, "public", True)
    for key in ("allowed", "owners", "nonsense"):
        with pytest.raises(ValueError):
            await cog.set_toggle(member.id, key, True)

    settings = await cog.settings_for(member.id)
    assert settings["public"]["value"] is True
    assert settings["public"]["label"] == "Public Use Slut"
    assert settings["allowed"]["value"] == []

    await member.send(channel, "!roleplay settings")
    prompt = _find_message(channel, bot, "Click the button to view your Roleplay settings.")
    shown = await member.click(prompt, label="Show Settings")
    assert shown.response is not None
    fields = [field.name for field in shown.response.embeds[0].fields]
    assert f"Public Use Slut {const.TRUE_EMOJI}" in fields
    assert f"Selective {const.FALSE_EMOJI}" in fields
    simcord.assert_no_errors(red_env)
