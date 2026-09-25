"""Tests for BanLog's message store, ban snapshots, dashboard API, and data deletion."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest
import pytest_asyncio

import banlog.banlog as banlog_module
from banlog.banlog import DELETED_MODERATOR_ID, GUILD_ID, BanLog, parse_moderator
from honeypot.honeypot import ENFORCEMENT_REASON
from moderation.moderation import audit_reason

BOT_ID = 900000000000000001
USER_ID = 100000000000000001
OTHER_ID = 100000000000000002
MOD_ID = 100000000000000003
DAY = 86400


@pytest_asyncio.fixture
async def cog(tmp_path) -> AsyncIterator[BanLog]:
    bot = MagicMock()
    bot.get_user.return_value = SimpleNamespace(name="spammer")
    cog = BanLog(bot)
    await cog._open(tmp_path / "banlog.sqlite3")
    yield cog
    await cog.db.close()


def _message(
    message_id: int,
    *,
    author_id: int = USER_ID,
    created: float | None = None,
    guild_id: int | None = GUILD_ID,
    bot: bool = False,
    webhook_id: int | None = None,
    content: str = "hello",
    attachments: tuple[str, ...] = (),
) -> Any:
    return SimpleNamespace(
        id=message_id,
        guild=None if guild_id is None else SimpleNamespace(id=guild_id),
        channel=SimpleNamespace(id=500),
        author=SimpleNamespace(id=author_id, bot=bot),
        webhook_id=webhook_id,
        content=content,
        attachments=[SimpleNamespace(filename=name) for name in attachments],
        created_at=datetime.fromtimestamp(created if created is not None else time.time(), UTC),
    )


def _edit(message_id: int, content: str) -> Any:
    return SimpleNamespace(
        guild_id=GUILD_ID, message=SimpleNamespace(id=message_id, content=content, edited_at=datetime.now(UTC))
    )


def _entry(action: discord.AuditLogAction, *, user_id: int | None = BOT_ID, reason: str | None = None) -> Any:
    return SimpleNamespace(
        guild=SimpleNamespace(id=GUILD_ID, me=SimpleNamespace(id=BOT_ID)),
        target=discord.Object(id=USER_ID),
        action=action,
        user_id=user_id,
        reason=reason,
        created_at=datetime.now(UTC),
    )


async def _rows(cog: BanLog, sql: str, *params: Any) -> list[dict[str, Any]]:
    async with cog.db.execute(sql, params) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


async def _store(cog: BanLog, *messages: Any) -> None:
    for message in messages:
        await cog.on_message(message)
    await cog._flush()


class _Author:
    id = MOD_ID

    def __str__(self) -> str:
        return "kirin"


# --- storage -----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_database_has_tables_and_indexes(cog: BanLog) -> None:
    names = {row["name"] for row in await _rows(cog, "SELECT name FROM sqlite_master")}

    assert {"messages", "bans", "ban_messages"} <= names
    assert {"messages_author_created", "messages_created", "bans_user", "bans_banned"} <= names


@pytest.mark.asyncio
async def test_insert_edit_and_delete_in_one_batch_apply_in_order(cog: BanLog) -> None:
    await cog.on_message(_message(1, content="original"))
    await cog.on_raw_message_edit(_edit(1, "edited"))
    await cog.on_raw_message_delete(cast(Any, SimpleNamespace(guild_id=GUILD_ID, message_id=1)))
    assert len(cog._ops) == 3

    await cog._flush()

    [row] = await _rows(cog, "SELECT * FROM messages")
    assert row["content"] == "original"
    assert row["edited_content"] == "edited"
    assert row["edited_at"] is not None
    assert row["deleted_at"] is not None
    assert cog._ops == []


@pytest.mark.asyncio
async def test_cancelled_flush_keeps_its_batch_for_the_next_one(cog: BanLog, monkeypatch: pytest.MonkeyPatch) -> None:
    await cog.on_message(_message(1))
    monkeypatch.setattr(cog.db, "execute", AsyncMock(side_effect=asyncio.CancelledError))

    with pytest.raises(asyncio.CancelledError):
        await cog._flush()
    monkeypatch.undo()
    await cog._flush()

    assert [row["id"] for row in await _rows(cog, "SELECT id FROM messages")] == [1]


@pytest.mark.asyncio
async def test_unload_writes_queued_messages(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(banlog_module, "cog_data_path", lambda cog: tmp_path)
    bot = MagicMock()
    bot.wait_until_red_ready = AsyncMock()
    cog = BanLog(bot)
    await cog.cog_load()
    await cog.on_message(_message(1))

    await cog.cog_unload()

    async with aiosqlite.connect(tmp_path / "banlog.sqlite3") as db, db.execute("SELECT id FROM messages") as cursor:
        assert await cursor.fetchall() == [(1,)]


# --- capture -----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_message_is_stored_without_files(cog: BanLog) -> None:
    await _store(cog, _message(1, content="look", attachments=("cat.png", "dog.gif")))

    [row] = await _rows(cog, "SELECT * FROM messages")
    assert (row["id"], row["channel_id"], row["author_id"], row["content"]) == (1, 500, USER_ID, "look")
    assert row["attachments"] == '["cat.png", "dog.gif"]'


@pytest.mark.parametrize(
    "message",
    [
        _message(1, bot=True),
        _message(1, webhook_id=77),
        _message(1, guild_id=None),
        _message(1, guild_id=123),
    ],
    ids=["bot", "webhook", "dm", "other-guild"],
)
@pytest.mark.asyncio
async def test_excluded_sources_are_not_stored(cog: BanLog, message: Any) -> None:
    await _store(cog, message)

    assert await _rows(cog, "SELECT * FROM messages") == []


@pytest.mark.asyncio
async def test_bulk_delete_marks_every_message(cog: BanLog) -> None:
    await _store(cog, _message(1), _message(2), _message(3))

    await cog.on_raw_bulk_message_delete(cast(Any, SimpleNamespace(guild_id=GUILD_ID, message_ids={1, 2})))
    await cog._flush()

    rows = await _rows(cog, "SELECT id, deleted_at FROM messages ORDER BY id")
    assert [row["deleted_at"] is not None for row in rows] == [True, True, False]


@pytest.mark.asyncio
async def test_prune_drops_week_old_messages_but_not_ban_records(cog: BanLog) -> None:
    now = time.time()
    old_ban = now - 730 * DAY
    await _store(cog, _message(1, created=old_ban - DAY))
    await cog.record_ban(USER_ID, "old", MOD_ID, "old ban", old_ban)
    await _store(cog, _message(2, created=now - 7 * DAY - 60), _message(3, created=now - 6 * DAY))

    await cog.prune(now)

    assert [row["id"] for row in await _rows(cog, "SELECT id FROM messages")] == [3]
    assert len(await _rows(cog, "SELECT * FROM bans")) == 1
    assert [row["id"] for row in await _rows(cog, "SELECT id FROM ban_messages")] == [1]


# --- bans --------------------------------------------------------------------------------------------


def test_parse_moderator_recovers_ban_command_author() -> None:
    reason = audit_reason(cast(Any, _Author()), "spam (again): links")

    assert parse_moderator(BOT_ID, reason, BOT_ID) == (MOD_ID, "spam (again): links")


def test_parse_moderator_keeps_other_bans_as_they_are() -> None:
    assert parse_moderator(BOT_ID, ENFORCEMENT_REASON, BOT_ID) == (BOT_ID, ENFORCEMENT_REASON)
    # A human typing the [p]ban format can't pin their ban on someone else.
    spoof = f"someone ({OTHER_ID}): framed"
    assert parse_moderator(MOD_ID, spoof, BOT_ID) == (MOD_ID, spoof)
    assert parse_moderator(None, None, BOT_ID) == (None, None)


@pytest.mark.asyncio
async def test_ban_snapshots_the_users_recent_messages(cog: BanLog) -> None:
    now = time.time()
    await _store(
        cog,
        _message(1, created=now - 8 * DAY),
        _message(2, created=now - 2 * DAY, content="bad link"),
        _message(3, author_id=OTHER_ID, created=now - DAY),
    )
    await cog.on_message(_message(4, created=now - 1, content="last words"))  # still queued at ban time
    reason = audit_reason(cast(Any, _Author()), "spam")

    await cog.on_audit_log_entry_create(_entry(discord.AuditLogAction.ban, reason=reason))

    [ban] = await _rows(cog, "SELECT * FROM bans")
    assert (ban["user_id"], ban["username"], ban["moderator_id"], ban["reason"]) == (USER_ID, "spammer", MOD_ID, "spam")
    record = await cog.get_ban(ban["id"])
    assert record is not None
    assert [message["content"] for message in record["messages"]] == ["bad link", "last words"]


@pytest.mark.asyncio
async def test_ban_without_messages_still_creates_a_record(cog: BanLog) -> None:
    bot = cast(MagicMock, cog.bot)
    bot.get_user.return_value = None
    bot.fetch_user = AsyncMock(return_value=SimpleNamespace(name="fetched"))

    await cog.on_audit_log_entry_create(_entry(discord.AuditLogAction.ban, user_id=MOD_ID, reason="raid"))

    [ban] = await _rows(cog, "SELECT * FROM bans")
    assert (ban["username"], ban["moderator_id"], ban["reason"]) == ("fetched", MOD_ID, "raid")
    assert await _rows(cog, "SELECT * FROM ban_messages") == []


@pytest.mark.asyncio
async def test_unban_closes_the_latest_open_record(cog: BanLog) -> None:
    now = time.time()
    first = await cog.record_ban(USER_ID, "a", MOD_ID, None, now - 30 * DAY)
    await cog.record_unban(USER_ID, now - 20 * DAY)
    second = await cog.record_ban(USER_ID, "a", MOD_ID, None, now - DAY)

    await cog.on_audit_log_entry_create(_entry(discord.AuditLogAction.unban))

    unbanned = {row["id"]: row["unbanned_at"] for row in await _rows(cog, "SELECT * FROM bans")}
    assert unbanned[first] == pytest.approx(now - 20 * DAY)
    assert unbanned[second] is not None and unbanned[second] > now - 60


@pytest.mark.asyncio
async def test_unban_without_a_record_changes_nothing(cog: BanLog) -> None:
    await cog.on_audit_log_entry_create(_entry(discord.AuditLogAction.unban))

    assert await _rows(cog, "SELECT * FROM bans") == []


@pytest.mark.parametrize("allowed", [True, False])
def test_warns_when_audit_log_is_hidden(cog: BanLog, caplog: pytest.LogCaptureFixture, allowed: bool) -> None:
    guild = SimpleNamespace(me=SimpleNamespace(guild_permissions=SimpleNamespace(view_audit_log=allowed)))
    cast(MagicMock, cog.bot).get_guild.return_value = guild

    with caplog.at_level(logging.WARNING, logger="red.kirin-cogs.banlog"):
        cog._check_audit_permission()

    assert ("View Audit Log" in caplog.text) is not allowed


# --- dashboard API -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_bans_pages_newest_first(cog: BanLog) -> None:
    for n in range(51):
        await cog.record_ban(USER_ID + n, f"user{n}", MOD_ID, None, 1000.0 + n)

    first, more = await cog.list_bans(0)
    second, more_after = await cog.list_bans(1)

    assert len(first) == 50 and more
    assert first[0]["username"] == "user50"
    assert [row["username"] for row in second] == ["user0"] and not more_after


@pytest.mark.asyncio
async def test_list_bans_searches_by_id_and_by_name(cog: BanLog) -> None:
    await cog.record_ban(USER_ID, "100%legit", MOD_ID, None, 1.0)
    await cog.record_ban(USER_ID, "100%legit", MOD_ID, None, 2.0)
    await cog.record_ban(OTHER_ID, "1000legit", MOD_ID, None, 3.0)

    by_id, _ = await cog.list_bans(0, str(USER_ID))
    by_name, _ = await cog.list_bans(0, "0%L")

    assert [row["banned_at"] for row in by_id] == [2.0, 1.0]
    assert {row["user_id"] for row in by_name} == {USER_ID}


@pytest.mark.asyncio
async def test_get_ban_of_unknown_id_is_none(cog: BanLog) -> None:
    assert await cog.get_ban(12345) is None


# --- data deletion -----------------------------------------------------------------------------------


async def _deletion_fixture(cog: BanLog) -> None:
    await _store(cog, _message(1), _message(2, author_id=OTHER_ID))
    await cog.record_ban(USER_ID, "spammer", MOD_ID, None, time.time())
    await cog.record_ban(OTHER_ID, "other", USER_ID, None, time.time())


@pytest.mark.asyncio
async def test_user_request_keeps_ban_records(cog: BanLog) -> None:
    await _deletion_fixture(cog)

    await cog.red_delete_data_for_user(requester="user", user_id=USER_ID)

    assert [row["author_id"] for row in await _rows(cog, "SELECT author_id FROM messages")] == [OTHER_ID]
    assert {row["user_id"] for row in await _rows(cog, "SELECT user_id FROM bans")} == {USER_ID, OTHER_ID}
    assert len(await _rows(cog, "SELECT * FROM ban_messages WHERE author_id = ?", USER_ID)) == 1


@pytest.mark.parametrize("requester", ["user_strict", "owner", "discord_deleted_user"])
@pytest.mark.asyncio
async def test_strict_requests_remove_ban_records_and_moderator_credit(cog: BanLog, requester: Any) -> None:
    await _deletion_fixture(cog)

    await cog.red_delete_data_for_user(requester=requester, user_id=USER_ID)

    assert [row["author_id"] for row in await _rows(cog, "SELECT author_id FROM messages")] == [OTHER_ID]
    [ban] = await _rows(cog, "SELECT * FROM bans")
    assert (ban["user_id"], ban["moderator_id"]) == (OTHER_ID, DELETED_MODERATOR_ID)
    assert await _rows(cog, "SELECT * FROM ban_messages WHERE author_id = ?", USER_ID) == []
