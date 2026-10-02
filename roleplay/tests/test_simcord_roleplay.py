"""Roleplay on a real Red instance driven through SimCord.

Covers the Discord-facing half of the cog: the dynamically registered action
commands, the consent question's Yes/No buttons, and the settings commands the
consent decisions are driven by. The consent decision table itself is pure
logic and already covered by test_roleplay_decide.py.
"""

from pathlib import Path
from typing import cast

import discord
import pytest
import simcord
from redbot.core.bot import Red
from redbot.core.tree import RedTree

from roleplay import const
from roleplay.main import Roleplay


@pytest.fixture
def red_cogs() -> list[str]:
    return ["roleplay"]


@pytest.fixture
def images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tiny stand-in gifs for hug and suck, served as the cog's image folder."""
    for name in ("hug/hug_1.gif", "hug/hug_wlw_2.gif", "suck/suck_1.gif"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"GIF89a")
    monkeypatch.setattr(Roleplay, "images_path", property(lambda _self: tmp_path))
    return tmp_path


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


def _assert_question_deleted(channel: simcord.ChannelHandle, bot: Red, text: str) -> None:
    assert not any(text in (m.content or "") for m in _bot_messages(channel, bot))


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
    assert "**!sadhug**" in (actions_field.value or "")
    assert len(actions_field.value or "") <= 1024
    assert any(f.name == "Pairings" for f in embed.fields)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_action_without_target_is_performed_by_the_bot(red_env: simcord.Env, images: Path) -> None:
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
    # without a pairing the wlw gif is never used
    assert embed.image is not None
    assert embed.image.url == "attachment://hug_1.gif"
    assert [a.filename for a in messages[0].attachments] == ["hug_1.gif"]
    assert "yet" not in (embed.footer.text or "")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_pairing_picks_the_tagged_gif(red_env: simcord.Env, images: Path) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!hug WLW")

    (message,) = _bot_messages(channel, bot)
    assert [a.filename for a in message.attachments] == ["hug_wlw_2.gif"]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_missing_pairing_falls_back_with_a_note(red_env: simcord.Env, images: Path) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!hug mlm")

    (message,) = _bot_messages(channel, bot)
    assert [a.filename for a in message.attachments] == ["hug_1.gif"]
    assert "No mlm gifs for hug yet" in (message.embeds[0].footer.text or "")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_spoilered_action_spoilers_any_file(red_env: simcord.Env, images: Path) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!suck wlw")

    (message,) = _bot_messages(channel, bot)
    assert not message.embeds
    assert [a.filename for a in message.attachments] == ["SPOILER_suck_1.gif"]
    assert message.content.endswith("\n-# No wlw gifs for suck yet, so here's another one.")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_action_without_images_is_still_performed(red_env: simcord.Env, images: Path) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!pat")

    (message,) = _bot_messages(channel, bot)
    assert _member(member).mention in (message.embeds[0].description or "")
    assert not message.attachments
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_alias_reaches_the_new_hug_actions(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    question = await _ask_action(channel, bot, hugger, "hugsad", target)

    assert "wants to give you a sad hug" in question.content
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
    _assert_question_deleted(channel, bot, "Do you consent?")
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
    _assert_question_deleted(channel, bot, "Do you consent?")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_an_owned_targets_owner_is_asked_instead(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = _cog(red_env)
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    owner = guild.add_member(red_env.create_user("owner"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await cog.user_settings.config.user(_member(target)).owners.set([owner.id])

    question = await _ask_action(channel, bot, hugger, "hug", target)

    assert _member(owner).mention in question.content
    assert _member(target).mention not in question.content
    assert "**target**" in question.content
    turned_away = await target.click(question, label="Yes")
    assert turned_away.response is not None
    assert turned_away.response.content == "This question isn't for you."

    await owner.click(question, label="Yes")

    assert any(m.embeds for m in _bot_messages(channel, bot))
    _assert_question_deleted(channel, bot, "Do you consent?")
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
    _assert_question_deleted(channel, bot, "Do you consent?")
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
async def test_ask_passes_the_action_to_the_target(red_env: simcord.Env, images: Path) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    requester = guild.add_member(red_env.create_user("requester"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await requester.send(channel, f"!ask hug wlw {_member(target).mention}")
    question = _find_message(channel, bot, "Do you consent?")
    assert "**requester** wants you to hug them" in question.content

    await target.click(question, label="Yes")

    # Passive tense swaps the parties: the target is the one hugging.
    action = next(m for m in _bot_messages(channel, bot) if m.embeds)
    description = action.embeds[0].description or ""
    assert description.index(_member(target).mention) < description.index(_member(requester).mention)
    assert [a.filename for a in action.attachments] == ["hug_wlw_2.gif"]
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
async def test_settings_slash_command_answers_ephemerally_without_a_button(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    admin = guild.add_member(red_env.create_user("admin"))
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    cast(set[int], bot.owner_ids).add(admin.id)  # what Red's --owner flag does
    await admin.send(channel, "!slash enable roleplay")
    await admin.send(channel, "!slash sync")

    shown = await member.slash(channel, "roleplay settings")

    assert shown.response is not None
    assert shown.response.ephemeral
    assert shown.response.embeds[0].title == "Roleplay Settings (member):"
    assert not any("Click the button" in (m.content or "") for m in _bot_messages(channel, bot))
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


@pytest.mark.asyncio
async def test_listed_users_the_bot_cannot_see_can_still_be_removed(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = _cog(red_env)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    # Neither shares a server with the bot, the way a listed user is after leaving
    old_owner = red_env.create_user("oldowner")
    gone = red_env.create_user("gone")
    await red_env.settle()
    config = cog.user_settings.config.user(_member(member))
    await config.owners.set([old_owner.id])
    await config.allowed.set([gone.id])
    assert bot.get_user(old_owner.id) is None

    await member.send(channel, f"!roleplay settings owners remove {old_owner.id}")
    assert "oldowner has been removed as an Owner for member." in (_bot_messages(channel, bot)[-1].content or "")
    await member.send(channel, "!roleplay settings allowed remove gone")
    assert "gone has been removed as an Allowed Users for member." in (_bot_messages(channel, bot)[-1].content or "")

    assert await config.owners() == []
    assert await config.allowed() == []
    simcord.assert_no_errors(red_env)


async def _enable_slash(env: simcord.Env, guild: simcord.GuildHandle, channel: simcord.ChannelHandle) -> None:
    """Enable and sync the cog's slash commands, as the owner does once with [p]slash."""
    owner = guild.add_member(env.create_user("owner"))
    await env.settle()
    cast(set[int], cast(Red, env.bot).owner_ids).add(owner.id)  # what Red's --owner flag does
    await owner.send(channel, "!slash enablecog roleplay")
    await owner.send(channel, "!slash sync")


@pytest.mark.asyncio
async def test_slash_action_with_a_pairing_asks_then_posts_the_tagged_gif(red_env: simcord.Env, images: Path) -> None:
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await _enable_slash(red_env, guild, channel)

    result = await hugger.slash(channel, "hug", pairing="wlw", member=target)

    assert result.deferred
    question = next(m for m in result.followups if "Do you consent?" in (m.content or ""))
    await target.click(question.message, label="Yes")

    action = next(m for m in result.followups if m.embeds)
    assert _member(hugger).mention in (action.embeds[0].description or "")
    assert [a.filename for a in action.attachments] == ["hug_wlw_2.gif"]
    _assert_question_deleted(channel, cast(Red, red_env.bot), "Do you consent?")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_slash_ask_passes_the_action_and_pairing(red_env: simcord.Env, images: Path) -> None:
    guild = red_env.create_guild()
    requester = guild.add_member(red_env.create_user("requester"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await _enable_slash(red_env, guild, channel)

    choices = await requester.autocomplete(channel, "ask", "action", "HU")
    assert {"hug", "sadhug", "happyhug"} <= {choice["value"] for choice in choices}

    result = await requester.slash(channel, "ask", action="hug", pairing="wlw", member=target)
    question = next(m for m in result.followups if "Do you consent?" in (m.content or ""))
    assert "**requester** wants you to hug them" in (question.content or "")
    await target.click(question.message, label="Yes")

    action = next(m for m in result.followups if m.embeds)
    assert [a.filename for a in action.attachments] == ["hug_wlw_2.gif"]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_slash_actions_survive_a_cog_reload(red_env: simcord.Env, images: Path) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await _enable_slash(red_env, guild, channel)

    await bot.remove_cog("Roleplay")
    await bot.add_cog(Roleplay(bot))
    await cast(RedTree, bot.tree).red_check_enabled()  # what Red's load_extension does after setup

    # No member: the bot hugs the invoker, no consent question needed.
    result = await member.slash(channel, "hug")
    action = next(m for m in result.followups if m.embeds)
    assert [a.filename for a in action.attachments] == ["hug_1.gif"]
    simcord.assert_no_errors(red_env)


def _field_names(result: simcord.InteractionResult) -> list[str]:
    assert result.response is not None
    return [field.name or "" for field in result.response.embeds[0].fields]


@pytest.mark.asyncio
async def test_dashboard_button_toggles_a_setting(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await _enable_slash(red_env, guild, channel)

    shown = await member.slash(channel, "roleplay settings")
    assert shown.response is not None and shown.response.ephemeral

    clicked = await member.click(shown.response.message, custom_id="roleplay:toggle:public")

    assert await cog.user_settings.config.user(_member(member)).public() is True
    assert f"Public Use Slut {const.TRUE_EMOJI}" in _field_names(clicked)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_dashboard_dropdowns_add_and_remove_listed_users(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    friend = guild.add_member(red_env.create_user("friend"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await _enable_slash(red_env, guild, channel)
    config = cog.user_settings.config.user(_member(member))

    shown = await member.slash(channel, "roleplay settings")
    assert shown.response is not None
    added = await member.select(shown.response.message, [friend], custom_id="roleplay:add:allowed")

    assert await config.allowed() == [friend.id]
    assert added.response is not None
    removed = await member.select(added.response.message, [f"allowed:{friend.id}"], custom_id="roleplay:remove")

    assert await config.allowed() == []
    assert removed.response is not None
    assert not any(
        c.get("custom_id") == "roleplay:remove" for row in removed.response.components for c in row["components"]
    )
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_dashboard_asks_the_new_owner_in_the_channel(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = _cog(red_env)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    owner = guild.add_member(red_env.create_user("owner2"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await _enable_slash(red_env, guild, channel)

    shown = await member.slash(channel, "roleplay settings")
    assert shown.response is not None
    await member.select(shown.response.message, [owner], custom_id="roleplay:add:owners")

    # The question waits in the channel, where the owner can see it
    question = _find_message(channel, bot, "would like you to be their Owner")
    await owner.click(question, label="Yes")
    await red_env.settle()

    assert await cog.user_settings.config.user(_member(member)).owners() == [owner.id]
    _assert_question_deleted(channel, bot, "would like you to be their Owner")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_settings_button_only_opens_for_whoever_asked(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = _cog(red_env)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    other = guild.add_member(red_env.create_user("other"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!roleplay settings")
    prompt = _find_message(channel, bot, "Click the button to view your Roleplay settings.")

    turned_away = await other.click(prompt, label="Show Settings")
    assert turned_away.response is not None
    assert turned_away.response.content == "These aren't your settings."

    shown = await member.click(prompt, label="Show Settings")
    assert shown.response is not None
    await member.click(shown.response.message, custom_id="roleplay:toggle:servant")
    assert await cog.user_settings.config.user(_member(member)).servant() is True
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_always_allowed_actions_skip_the_question(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = _cog(red_env)
    guild = red_env.create_guild()
    hugger = guild.add_member(red_env.create_user("hugger"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await target.send(channel, "!roleplay settings actions add Hug pets")
    assert "`hug` and `pat`" in (_bot_messages(channel, bot)[-1].content or "")
    assert await cog.user_settings.config.user(_member(target)).consented_actions() == ["hug", "pat"]

    await hugger.send(channel, f"!hug {_member(target).mention}")
    assert _bot_messages(channel, bot)[-1].embeds
    assert not any("Do you consent?" in (m.content or "") for m in _bot_messages(channel, bot))

    await hugger.send(channel, f"!kiss {_member(target).mention}")
    assert "Do you consent?" in (_bot_messages(channel, bot)[-1].content or "")

    await target.send(channel, "!roleplay settings actions remove pet")
    assert await cog.user_settings.config.user(_member(target)).consented_actions() == ["hug"]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_pet_is_pat_and_a_saved_pet_consent_counts_for_it(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = _cog(red_env)
    guild = red_env.create_guild()
    petter = guild.add_member(red_env.create_user("petter"))
    target = guild.add_member(red_env.create_user("target"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    # saved before pet became an alias of pat
    await cog.user_settings.config.user(_member(target)).consented_actions.set(["pet"])

    assert cog.action_manager.get("pet") is cog.action_manager.get("pat")
    assert await cog.user_settings.consented_actions(_member(target)) == ["pat"]
    await petter.send(channel, f"!pet {_member(target).mention}")
    assert _bot_messages(channel, bot)[-1].embeds
    assert not any("Do you consent?" in (m.content or "") for m in _bot_messages(channel, bot))
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_dashboard_picks_always_allowed_actions(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await _enable_slash(red_env, guild, channel)
    config = cog.user_settings.config.user(_member(member))

    shown = await member.slash(channel, "roleplay settings")
    assert shown.response is not None
    picker = await member.click(shown.response.message, custom_id="roleplay:actions")
    assert picker.response is not None and picker.response.ephemeral

    # hug and walk sit in different dropdowns; picking in one keeps the other's picks
    await member.select(picker.response.message, ["hug"], custom_id="roleplay:actions:0")
    await member.select(picker.response.message, ["walk"], custom_id="roleplay:actions:1")
    assert await config.consented_actions() == ["hug", "walk"]

    await member.select(picker.response.message, [], custom_id="roleplay:actions:1")
    assert await config.consented_actions() == ["hug"]
    simcord.assert_no_errors(red_env)
