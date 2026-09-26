"""Keep a rolling 7-day copy of Unicornia's messages and snapshot a banned user's messages into a permanent record.

Discord purges a banned user's messages without sending any delete event, so this copy is the only record left.
"""

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
import discord
from discord.ext import tasks
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

GUILD_ID = 684360255798509578
RETENTION_SECONDS = 7 * 86400  # the longest window a ban can purge
FLUSH_SECONDS = 5
FLUSH_AT = 200
PAGE_SIZE = 50
DELETED_MODERATOR_ID = 0xDE1  # the placeholder moderation uses for deleted moderators
# [p]ban's audit reason, built by moderation.audit_reason: "{author} ({author_id}): {reason}"
MOD_REASON = re.compile(r"^.+? \((\d{15,20})\): (.*)$", re.DOTALL)

MESSAGE_COLUMNS = "id, channel_id, author_id, created_at, content, edited_content, edited_at, deleted_at, attachments"
SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    content TEXT NOT NULL,
    edited_content TEXT,
    edited_at REAL,
    deleted_at REAL,
    attachments TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_author_created ON messages (author_id, created_at);
CREATE INDEX IF NOT EXISTS messages_created ON messages (created_at);
CREATE TABLE IF NOT EXISTS bans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    moderator_id INTEGER,
    reason TEXT,
    banned_at REAL NOT NULL,
    unbanned_at REAL
);
CREATE INDEX IF NOT EXISTS bans_user ON bans (user_id);
CREATE INDEX IF NOT EXISTS bans_banned ON bans (banned_at);
CREATE TABLE IF NOT EXISTS ban_messages (
    ban_id INTEGER NOT NULL,
    id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    content TEXT NOT NULL,
    edited_content TEXT,
    edited_at REAL,
    deleted_at REAL,
    attachments TEXT NOT NULL,
    PRIMARY KEY (ban_id, id)
);
"""
INSERT_MESSAGE = (
    "INSERT OR IGNORE INTO messages (id, channel_id, author_id, created_at, content, attachments) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)
EDIT_MESSAGE = "UPDATE messages SET edited_content = ?, edited_at = ? WHERE id = ?"
DELETE_MESSAGE = "UPDATE messages SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL"

log = logging.getLogger("red.kirin-cogs.banlog")


def parse_moderator(moderator_id: int | None, reason: str | None, bot_id: int) -> tuple[int | None, str | None]:
    """Recover the staff member behind a bot-issued `[p]ban`; any other ban keeps the audit log's own moderator."""
    if moderator_id == bot_id and reason and (match := MOD_REASON.match(reason)):
        return int(match[1]), match[2]
    return moderator_id, reason


class BanLog(commands.Cog):
    """Keep what banned users said, even after Discord purges it."""

    db: aiosqlite.Connection

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        # Ordered message changes waiting to be written; order keeps an edit behind its own insert.
        self._ops: list[tuple[str, tuple[Any, ...]]] = []
        self._lock = asyncio.Lock()

    async def cog_load(self) -> None:
        await self._open(cog_data_path(self) / "banlog.sqlite3")
        self._flush_loop.start()
        self._hourly.start()

    async def cog_unload(self) -> None:
        self._flush_loop.cancel()
        self._hourly.cancel()
        await self._flush()  # waits for a cancelled write to hand back its batch, then writes everything
        await self.db.close()

    async def _open(self, path: Path) -> None:
        self.db = await aiosqlite.connect(path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA synchronous=NORMAL")
        await self.db.executescript(SCHEMA)
        await self.db.commit()
        # Every member's recent messages sit in here, so only the bot's own Unix user may read them.
        os.chmod(path.parent, 0o700)
        os.chmod(path, 0o600)

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Write the queued message changes, then the caller's writes, as one transaction."""
        async with self._lock:
            ops, self._ops = self._ops, []
            try:
                for sql, params in ops:
                    await self.db.execute(sql, params)
                yield self.db
                await self.db.commit()
            except BaseException:
                # Keep the batch for the next flush (or unload's final flush, if cancelled).
                self._ops[:0] = ops
                await self.db.rollback()
                raise

    async def _flush(self) -> None:
        try:
            async with self._transaction():
                pass
        except Exception:
            log.exception("Could not write queued messages to the ban log")

    async def _queue(self, sql: str, *params: Any) -> None:
        self._ops.append((sql, params))
        if len(self._ops) >= FLUSH_AT:
            await self._flush()

    @tasks.loop(seconds=FLUSH_SECONDS)
    async def _flush_loop(self) -> None:
        await self._flush()

    @tasks.loop(hours=1)
    async def _hourly(self) -> None:
        try:
            await self.prune()
        except Exception:
            log.exception("Could not prune the ban log's message store")
        self._check_audit_permission()

    @_hourly.before_loop
    async def _before_hourly(self) -> None:
        await self.bot.wait_until_red_ready()

    async def prune(self, now: float | None = None) -> None:
        """Drop stored messages older than the retention window; ban records keep their own copies."""
        cutoff = (now or time.time()) - RETENTION_SECONDS
        async with self._transaction() as db:
            await db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))

    def _check_audit_permission(self) -> None:
        guild = self.bot.get_guild(GUILD_ID)
        if guild is not None and not guild.me.guild_permissions.view_audit_log:
            log.warning("The bot lacks View Audit Log in Unicornia, so bans are not being recorded")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        if after.guild.id == GUILD_ID and after in after.guild.me.roles:
            self._check_audit_permission()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.guild.id == GUILD_ID and after.id == after.guild.me.id and before.roles != after.roles:
            self._check_audit_permission()

    # --- capture ---------------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.guild.id != GUILD_ID or message.author.bot or message.webhook_id:
            return
        attachments = json.dumps([attachment.filename for attachment in message.attachments])
        created = message.created_at.timestamp()
        await self._queue(
            INSERT_MESSAGE, message.id, message.channel.id, message.author.id, created, message.content, attachments
        )

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        message = payload.message
        if payload.guild_id != GUILD_ID or message.edited_at is None:
            return  # embeds unfurling fire this event too, without an edit time
        await self._queue(EDIT_MESSAGE, message.content, message.edited_at.timestamp(), message.id)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        if payload.guild_id == GUILD_ID:
            await self._queue(DELETE_MESSAGE, time.time(), payload.message_id)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        if payload.guild_id == GUILD_ID:
            now = time.time()
            for message_id in payload.message_ids:
                await self._queue(DELETE_MESSAGE, now, message_id)

    # --- bans --------------------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        """Bans from any source ([p]ban, Honeypot, Discord's menus, other bots) all land in the audit log."""
        target = entry.target
        if entry.guild.id != GUILD_ID or not isinstance(target, discord.Object | discord.User | discord.Member):
            return
        when = entry.created_at.timestamp()
        if entry.action is discord.AuditLogAction.ban:
            moderator_id, reason = parse_moderator(entry.user_id, entry.reason, entry.guild.me.id)
            await self.record_ban(target.id, await self._username(target), moderator_id, reason, when)
        elif entry.action is discord.AuditLogAction.unban:
            await self.record_unban(target.id, when)

    async def _username(self, target: discord.Object | discord.User | discord.Member) -> str | None:
        user = target if isinstance(target, discord.User | discord.Member) else self.bot.get_user(target.id)
        if user is None:
            try:
                user = await self.bot.fetch_user(target.id)
            except discord.HTTPException:
                return None
        return user.name

    async def record_ban(
        self, user_id: int, username: str | None, moderator_id: int | None, reason: str | None, banned_at: float
    ) -> int:
        """Create a permanent ban record holding the user's stored messages from the week before the ban."""
        # The transaction writes queued messages first, so one sent a second before the ban is included.
        async with self._transaction() as db:
            cursor = await db.execute(
                "INSERT INTO bans (user_id, username, moderator_id, reason, banned_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, moderator_id, reason, banned_at),
            )
            ban_id = cursor.lastrowid
            await db.execute(
                f"INSERT INTO ban_messages (ban_id, {MESSAGE_COLUMNS}) SELECT ?, {MESSAGE_COLUMNS} FROM messages "
                "WHERE author_id = ? AND created_at >= ?",
                (ban_id, user_id, banned_at - RETENTION_SECONDS),
            )
        assert ban_id is not None
        return ban_id

    async def record_unban(self, user_id: int, unbanned_at: float) -> None:
        async with self._transaction() as db:
            await db.execute(
                "UPDATE bans SET unbanned_at = ? WHERE id = (SELECT id FROM bans WHERE user_id = ? "
                "AND unbanned_at IS NULL ORDER BY banned_at DESC, id DESC LIMIT 1)",
                (unbanned_at, user_id),
            )

    # --- API for the dashboard -----------------------------------------------------------------------

    async def list_bans(self, page: int = 0, query: str = "") -> tuple[list[dict[str, Any]], bool]:
        """One page of ban records, newest first, and whether another page follows.

        A number matches a user ID exactly; anything else matches part of the username.
        """
        if query.isdecimal() and int(query) < 2**63:
            where, params = "WHERE user_id = ?", [int(query)]
        elif query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where, params = "WHERE username LIKE ? ESCAPE '\\'", [f"%{escaped}%"]
        else:
            where, params = "", []
        async with self.db.execute(
            "SELECT *, (SELECT COUNT(*) FROM ban_messages WHERE ban_id = bans.id) AS message_count "
            f"FROM bans {where} ORDER BY banned_at DESC, id DESC LIMIT ? OFFSET ?",
            (*params, PAGE_SIZE + 1, page * PAGE_SIZE),
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]
        return rows[:PAGE_SIZE], len(rows) > PAGE_SIZE

    async def get_ban(self, ban_id: int) -> dict[str, Any] | None:
        """A ban record with its captured messages, oldest first, or None when there is no such record."""
        async with self.db.execute("SELECT * FROM bans WHERE id = ?", (ban_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        ban = dict(row)
        async with self.db.execute(
            f"SELECT {MESSAGE_COLUMNS} FROM ban_messages WHERE ban_id = ? ORDER BY created_at, id", (ban_id,)
        ) as cursor:
            ban["messages"] = [
                {**dict(message), "attachments": json.loads(message["attachments"])}
                for message in await cursor.fetchall()
            ]
        return ban

    # --- data deletion -----------------------------------------------------------------------------

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Drop the user's stored messages; stricter requests also drop their ban records and moderator credit.

        A plain `user` request keeps ban records, which are moderation records rather than user content.
        """
        async with self._transaction() as db:
            await db.execute("DELETE FROM messages WHERE author_id = ?", (user_id,))
            if requester != "user":
                await db.execute(
                    "DELETE FROM ban_messages WHERE ban_id IN (SELECT id FROM bans WHERE user_id = ?)", (user_id,)
                )
                await db.execute("DELETE FROM bans WHERE user_id = ?", (user_id,))
                await db.execute(
                    "UPDATE bans SET moderator_id = ? WHERE moderator_id = ?", (DELETED_MODERATOR_ID, user_id)
                )
