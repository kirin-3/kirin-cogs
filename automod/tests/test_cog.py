import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from redbot.core.commands.requires import PrivilegeLevel

import automod.automod as module
from automod.automod import GUILD_ID, LOG_SIZE, AutoMod
from automod.tests.helpers import document, rule, ruleset, word_list
from testutils import DictGroup

BOT_ID, MEMBER_ID = 1, 7


class FakeConfig(DictGroup):
    def register_global(self, **defaults: Any) -> None:
        self._store.update(defaults)


@pytest.fixture
def cog(monkeypatch: pytest.MonkeyPatch) -> AutoMod:
    monkeypatch.setattr(module.Config, "get_conf", lambda *a, **k: FakeConfig({}))
    monkeypatch.setattr(AutoMod, "sweep", MagicMock())
    bot = MagicMock()
    bot.user.id = BOT_ID
    bot.is_owner = AsyncMock(return_value=True)
    return AutoMod(bot)


def _member(member_id: int = MEMBER_ID, nick: str | None = None) -> MagicMock:
    member = MagicMock(spec=discord.Member, id=member_id, bot=False, roles=[], nick=nick, global_name=None)
    member.name = "member"
    member.mention = f"<@{member_id}>"
    member.configure_mock(**{"__str__.return_value": "member"})
    member.guild.id = GUILD_ID
    member.guild.me = SimpleNamespace(id=BOT_ID)
    member.guild.get_role.return_value = object()
    member.edit = AsyncMock()
    return member


def _message(text: str, member: MagicMock | None = None, guild_id: int = GUILD_ID) -> MagicMock:
    member = member or _member()
    member.guild.id = guild_id
    message = MagicMock(spec=discord.Message, content=text, webhook_id=None, attachments=[])
    message.author = member
    message.guild = member.guild
    message.is_system.return_value = False
    message.channel = MagicMock(spec=discord.TextChannel, id=10)
    message.channel.send = AsyncMock()
    message.raw_mentions, message.raw_role_mentions = [], []
    message.delete = AsyncMock()
    message.edited_at = None
    return message


def _moderation(error: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        mute_member=AsyncMock(return_value=error),
        warn_member=AsyncMock(return_value=None),
        timeout_member=AsyncMock(return_value=None),
        ban_user=AsyncMock(return_value=None),
    )


INVITE_RULES = document(
    ruleset(
        "invite",
        [rule("invite", [{"type": "invite"}], [{"type": "delete"}, {"type": "mute", "minutes": 1440, "reason": ""}])],
    )
)


async def _load(cog: AutoMod, doc: dict = INVITE_RULES, dry_run: bool = False) -> None:
    await cog.cog_load()
    await cog.save(doc)
    await cog.set_dry_run(dry_run)


@pytest.mark.asyncio
async def test_fresh_install_is_empty_and_in_dry_run(cog: AutoMod) -> None:
    await cog.cog_load()
    assert await cog.document() == {"rulesets": [], "lists": [], "next_id": 1}
    assert cog.dry_run is True
    await cog.on_message(_message("discord.gg/abc"))
    assert await cog.action_log() == []


@pytest.mark.asyncio
async def test_save_swaps_the_snapshot_and_bad_saves_change_nothing(cog: AutoMod) -> None:
    await _load(cog)
    assert [r.name for r in cog.snapshot.rules] == ["invite"]
    before = await cog.document()
    bad = document(ruleset("x", [rule("no triggers", [])]))
    with pytest.raises(module.RuleError):
        await cog.save(bad)
    assert await cog.document() == before
    assert [r.name for r in cog.snapshot.rules] == ["invite"]


@pytest.mark.asyncio
async def test_invalid_stored_rules_leave_automod_running_empty(cog: AutoMod) -> None:
    await cog.config.rules.set({"rulesets": [{"name": "broken"}], "lists": []})
    await cog.cog_load()
    assert cog.snapshot.rules == ()


@pytest.mark.asyncio
async def test_other_guilds_and_the_bot_itself_are_ignored(cog: AutoMod) -> None:
    await _load(cog)
    await cog.on_message(_message("discord.gg/abc", guild_id=123))
    await cog.on_message(_message("discord.gg/abc", _member(BOT_ID)))
    webhook = _message("discord.gg/abc")
    webhook.webhook_id = 5
    await cog.on_message(webhook)
    assert await cog.action_log() == []


@pytest.mark.asyncio
async def test_edits_only_count_when_the_text_changed(cog: AutoMod) -> None:
    await _load(cog, dry_run=True)
    preview = _message("discord.gg/abc")  # Discord adding an embed: no edited_at
    await cog.on_raw_message_edit(SimpleNamespace(guild_id=GUILD_ID, message=preview, cached_message=None))  # type: ignore[arg-type]
    assert await cog.action_log() == []

    edited = _message("now with discord.gg/abc")
    edited.edited_at = datetime.now(UTC)
    cached = SimpleNamespace(content="hello")
    await cog.on_raw_message_edit(SimpleNamespace(guild_id=GUILD_ID, message=edited, cached_message=cached))  # type: ignore[arg-type]
    [entry] = await cog.action_log()
    assert entry["event"] == "edit"


@pytest.mark.asyncio
async def test_dry_run_logs_without_acting_and_keeps_no_text(cog: AutoMod) -> None:
    await _load(cog, dry_run=True)
    moderation = _moderation()
    cog.bot.get_cog.return_value = moderation
    message = _message("secret words discord.gg/abc")
    await cog.on_message(message)

    message.delete.assert_not_awaited()
    moderation.mute_member.assert_not_awaited()
    [entry] = await cog.action_log()
    assert [(a["type"], a["status"]) for a in entry["actions"]] == [("delete", "would"), ("mute", "would")]
    assert entry["rules"] == [{"ruleset": "invite", "rule": "invite", "trigger": "Server invite"}]
    assert "secret" not in json.dumps(entry)
    assert "discord.gg" not in json.dumps(entry)


@pytest.mark.asyncio
async def test_member_above_the_bot_is_deleted_but_not_muted(cog: AutoMod) -> None:
    await _load(cog)
    moderation = _moderation("My highest role isn't above theirs.")
    cog.bot.get_cog.return_value = moderation
    message = _message("discord.gg/abc")
    await cog.on_message(message)

    message.delete.assert_awaited_once()
    args = moderation.mute_member.await_args
    assert args.kwargs == {"keep_longer": True}
    assert args.args[2] == "Automod: invite / invite"  # the default reason
    [entry] = await cog.action_log()
    assert entry["actions"][1] == {
        "rule": "invite / invite",
        "type": "mute",
        "status": "failed",
        "error": "My highest role isn't above theirs.",
    }


@pytest.mark.asyncio
async def test_unloaded_moderation_cog_fails_only_that_action(cog: AutoMod) -> None:
    await _load(cog)
    cog.bot.get_cog.return_value = None
    message = _message("discord.gg/abc")
    await cog.on_message(message)
    [entry] = await cog.action_log()
    assert [a["status"] for a in entry["actions"]] == ["done", "failed"]


@pytest.mark.asyncio
async def test_setting_a_nickname_does_not_loop(cog: AutoMod) -> None:
    nick = {"type": "nickname", "nickname": "Change Your Nickname"}
    await _load(
        cog, document(ruleset("name", [rule("kirin", [{"type": "name_regex", "pattern": "(?i)kirin"}], [nick])]))
    )
    before, after = _member(nick=None), _member(nick="KiRiN")
    await cog.on_member_update(before, after)
    after.edit.assert_awaited_once()
    assert after.edit.await_args.kwargs["nick"] == "Change Your Nickname"

    # Discord reports automod's own rename; the username still matches but nothing runs again.
    renamed = _member(nick="Change Your Nickname")
    renamed.name = "kirin_fan"
    await cog.on_member_update(after, renamed)
    renamed.edit.assert_not_awaited()
    assert len(await cog.action_log()) == 1


@pytest.mark.asyncio
async def test_send_message_with_ping_and_auto_delete(cog: AutoMod) -> None:
    send = {"type": "send", "text": "Check mod-log.", "ping": True, "delete_after": 30}
    await _load(cog, document(ruleset("s", [rule("r", [{"type": "invite"}], [send])])))
    message = _message("discord.gg/abc")
    cog.bot.get_cog.return_value = _moderation()
    await cog.on_message(message)
    call = message.channel.send.await_args
    assert call.args == ("<@7> Check mod-log.",)
    assert call.kwargs["delete_after"] == 30


@pytest.mark.asyncio
async def test_counts_reset_after_a_counted_rule_fires(cog: AutoMod) -> None:
    burst = {"type": "message_rate", "count": 3, "seconds": 60}
    await _load(cog, document(ruleset("spam", [rule("r", [burst], [{"type": "delete"}])])), dry_run=True)
    member = _member()
    for n in range(4):
        await cog.on_message(_message(f"m{n}", member))
    assert len(await cog.action_log()) == 1


@pytest.mark.asyncio
async def test_log_keeps_the_newest_250(cog: AutoMod) -> None:
    await cog.config.log.set([{"user_id": n} for n in range(LOG_SIZE)])
    await _load(cog, dry_run=True)
    await cog.on_message(_message("discord.gg/abc"))
    entries = await cog.action_log()
    assert len(entries) == LOG_SIZE
    assert entries[0]["user_id"] == MEMBER_ID
    assert entries[-1]["user_id"] == 1  # entry 0 was dropped


@pytest.mark.asyncio
async def test_data_deletion_removes_only_that_users_entries(cog: AutoMod) -> None:
    await cog.config.log.set([{"user_id": 5}, {"user_id": 9}, {"user_id": 5}, {"user_id": 5}])
    await cog.red_delete_data_for_user(requester="user", user_id=5)
    assert await cog.action_log() == [{"user_id": 9}]


def _ctx(attachments: list | None = None, guild: Any = None) -> MagicMock:
    ctx = MagicMock()
    ctx.message.attachments = attachments or []
    ctx.message.delete = AsyncMock()
    ctx.guild = guild
    ctx.send = AsyncMock()
    ctx.author.send = AsyncMock()
    return ctx


def _file(data: Any) -> MagicMock:
    attachment = MagicMock(size=100)
    attachment.read = AsyncMock(return_value=json.dumps(data).encode())
    return attachment


@pytest.mark.asyncio
async def test_import_and_export(cog: AutoMod) -> None:
    await cog.cog_load()
    ctx = _ctx()
    await AutoMod.automod_import.callback(cog, ctx)  # type: ignore[arg-type]
    assert "Attach the rules JSON file" in ctx.send.await_args.args[0]

    lists = [word_list("words", ["badword"], 900)]
    doc = document(ruleset("w", [rule("r", [{"type": "words", "list": 900}])]), lists=lists)
    ctx = _ctx([_file(doc)])
    await AutoMod.automod_import.callback(cog, ctx)  # type: ignore[arg-type]
    assert ctx.send.await_args.args[0] == "Imported 1 rulesets and 1 lists. Dry-run is on."
    stored = await cog.document()

    # Round trip: exporting and importing the export changes nothing.
    ctx = _ctx()
    await AutoMod.automod_export.callback(cog, ctx)  # type: ignore[arg-type]
    exported = json.loads(ctx.author.send.await_args.kwargs["file"].fp.read())
    await AutoMod.automod_import.callback(cog, _ctx([_file(exported)]))  # type: ignore[arg-type]
    assert await cog.document() == stored

    # A rule pointing at a list that isn't in the file is rejected.
    ctx = _ctx([_file({**doc, "lists": []})])
    await AutoMod.automod_import.callback(cog, ctx)  # type: ignore[arg-type]
    assert "Import failed, nothing changed. Ruleset 'w', rule 'r'" in ctx.send.await_args.args[0]
    assert await cog.document() == stored


def test_automod_commands_are_owner_only(cog: AutoMod) -> None:
    # Red checks a group's requirements before running any of its subcommands.
    assert cog.automod.requires.privilege_level is PrivilegeLevel.BOT_OWNER


@pytest.mark.asyncio
async def test_display_name_change_is_checked(cog: AutoMod) -> None:
    lists = [word_list("names", ["slur"], 900)]
    await _load(cog, document(ruleset("n", [rule("r", [{"type": "name_words", "list": 900}])]), lists=lists), True)
    member = _member()
    member.global_name = "a slur"
    cog.bot.get_guild.return_value.get_member.return_value = member
    await cog.on_user_update(
        SimpleNamespace(id=MEMBER_ID, name="member", global_name="fine"),  # type: ignore[arg-type]
        SimpleNamespace(id=MEMBER_ID, name="member", global_name="a slur"),  # type: ignore[arg-type]
    )
    [entry] = await cog.action_log()
    assert (entry["event"], entry["rules"][0]["trigger"]) == ("name", "Name word list")
