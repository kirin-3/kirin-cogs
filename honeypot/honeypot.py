"""Immediate containment for messages posted in Unicornia's honeypot channel."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify

GUILD_ID = 684360255798509578
HONEYPOT_CHANNEL_ID = 1542655461738938489
LOG_CHANNEL_ID = 1542663016452063366
STAFF_ROLE_ID = 696020813299580940
NEW_MEMBER_DAYS = 3
TIMEOUT_DAYS = 28
BAN_PURGE_SECONDS = 86400
APPEAL_URL = "https://forms.gle/SdrjyV9ggi3hBQbh8"

BAN_NOTICE = (
    "Your account appears to have been compromised and has been banned from Unicornia. "
    f"If you have recovered your account, you may appeal here: {APPEAL_URL}"
)
QUARANTINE_NOTICE = (
    "Your account was probably compromised and has been quarantined in Unicornia. "
    "If you recover it, please contact Modmail so staff can restore your access."
)

CONFIG_IDENTIFIER = 98245173605
EMBED_FIELD_LIMIT = 1024
ENFORCEMENT_REASON = "Posted in the Unicornia honeypot channel"

log = logging.getLogger("red.kirin-cogs.honeypot")


async def _staff_or_admin(ctx: commands.Context) -> bool:
    """Apply has-any-role OR Red-admin/manage-roles command semantics."""
    if ctx.guild is None:
        raise commands.NoPrivateMessage
    if not isinstance(ctx.author, discord.Member):
        return False
    if ctx.author.get_role(STAFF_ROLE_ID) is not None:
        return True
    if ctx.author.guild_permissions.manage_roles:
        return True
    if await ctx.bot.is_owner(ctx.author):
        return True
    return await ctx.bot.is_admin(ctx.author)


@dataclass
class _LockEntry:
    """A keyed lock and the number of coroutines holding or awaiting it."""

    lock: asyncio.Lock
    holders: int = 0


class Honeypot(commands.Cog):
    """Contain accounts that post in Unicornia's honeypot channel."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=CONFIG_IDENTIFIER, force_registration=True)
        self.config.register_guild(quarantined_users={})
        self._quarantine_locks: dict[tuple[int, int], _LockEntry] = {}
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._enforced_users: set[tuple[int, int]] = set()

    async def cog_unload(self) -> None:
        """Cancel work that still belongs to this cog."""
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()
        self._quarantine_locks.clear()
        self._enforced_users.clear()

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester: str, user_id: int
    ) -> None:
        """Remove a user's quarantine snapshot from every guild scope."""
        del requester
        for guild_id, data in (await self.config.all_guilds()).items():
            if not isinstance(data, dict):
                continue
            records = data.get("quarantined_users")
            if not isinstance(records, dict):
                continue
            matching_keys = [key for key in records if str(key) == str(user_id)]
            if not matching_keys:
                continue
            for key in matching_keys:
                records.pop(key, None)
            await self.config.guild_from_id(guild_id).quarantined_users.set(records)
            self._enforced_users.discard((guild_id, user_id))

    @asynccontextmanager
    async def _quarantine_lock(self, guild_id: int, user_id: int) -> AsyncGenerator[asyncio.Lock, None]:
        """Serialize enforcement for one guild member and remove idle locks."""
        key = (guild_id, user_id)
        entry = self._quarantine_locks.get(key)
        if entry is None:
            entry = _LockEntry(asyncio.Lock())
            self._quarantine_locks[key] = entry
        entry.holders += 1
        try:
            async with entry.lock:
                yield entry.lock
        finally:
            entry.holders -= 1
            if entry.holders == 0 and self._quarantine_locks.get(key) is entry:
                del self._quarantine_locks[key]

    def _create_task(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            log.error("Honeypot background task failed: %s", exception, exc_info=exception)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Start enforcement after the complete side-effect-free guard gauntlet."""
        guild = message.guild
        if guild is None or guild.id != GUILD_ID:
            return
        channel_id = getattr(message.channel, "id", None)
        parent_id = getattr(message.channel, "parent_id", None)
        if channel_id != HONEYPOT_CHANNEL_ID and parent_id != HONEYPOT_CHANNEL_ID:
            return
        if not isinstance(message.author, discord.Member):
            return
        if message.author.bot or message.webhook_id is not None:
            return
        member = message.author
        if any(role.id == STAFF_ROLE_ID for role in member.roles):
            return

        captured_content = message.content
        captured_identity = f"{member} ({member.id})"
        attachment_names = tuple(attachment.filename for attachment in message.attachments)
        self._create_task(self._handle_trigger(message, member, captured_identity, captured_content, attachment_names))

    async def _handle_trigger(
        self,
        message: discord.Message,
        member: discord.Member,
        captured_identity: str,
        captured_content: str,
        attachment_names: tuple[str, ...],
    ) -> None:
        guild = member.guild
        key = (guild.id, member.id)
        async with self._quarantine_lock(*key):
            await self._delete_trigger(message, guild, captured_identity)

            records = await self.config.guild(guild).quarantined_users()
            record = records.get(str(member.id)) if isinstance(records, dict) else None
            if isinstance(record, dict) and record.get("state", "completed") == "completed":
                self._enforced_users.add(key)
                return
            if key in self._enforced_users:
                return

            if member.id == guild.owner_id:
                await self._log_alert(
                    guild,
                    title="Honeypot owner alert",
                    member_identity=captured_identity,
                    action="enforcement",
                    detail="The guild owner triggered the honeypot and was not targeted.",
                )
                return

            tenure_days = self._tenure_days(member)
            if tenure_days is not None and tenure_days < NEW_MEMBER_DAYS:
                succeeded = await self._ban_member(
                    guild,
                    member,
                    captured_identity,
                    captured_content,
                    attachment_names,
                    tenure_days,
                )
            else:
                succeeded = await self._quarantine_member(
                    guild,
                    member,
                    captured_identity,
                    captured_content,
                    attachment_names,
                    record if isinstance(record, dict) else None,
                )
            if succeeded:
                self._enforced_users.add(key)

    async def _delete_trigger(self, message: discord.Message, guild: discord.Guild, member_identity: str) -> None:
        bot_member = guild.me
        if bot_member is not None and not bot_member.guild_permissions.manage_messages:
            await self._log_permission_failure(guild, member_identity, "message deletion", "manage_messages")
            return
        try:
            await message.delete()
        except discord.NotFound:
            log.info("Honeypot message %s was already deleted", message.id)
        except discord.Forbidden:
            await self._log_permission_failure(guild, member_identity, "message deletion", "manage_messages")
        except discord.HTTPException as exc:
            await self._log_alert(
                guild,
                title="Honeypot deletion failure",
                member_identity=member_identity,
                action="message deletion",
                detail=str(exc),
            )

    @staticmethod
    def _tenure_days(member: discord.Member) -> float | None:
        if member.joined_at is None:
            return None
        return (datetime.now(UTC) - member.joined_at).total_seconds() / 86400

    async def _ban_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        member_identity: str,
        captured_content: str,
        attachment_names: tuple[str, ...],
        tenure_days: float,
    ) -> bool:
        dm_delivered = await self._send_dm(member, BAN_NOTICE)
        target: discord.abc.Snowflake = member
        if guild.get_member(member.id) is None:
            target = discord.Object(id=member.id)
        try:
            await guild.ban(target, reason=ENFORCEMENT_REASON, delete_message_seconds=BAN_PURGE_SECONDS)
        except discord.Forbidden:
            bot_member = guild.me
            if bot_member is not None and not bot_member.guild_permissions.ban_members:
                await self._log_permission_failure(guild, member_identity, "ban", "ban_members")
            else:
                await self._log_alert(
                    guild,
                    title="Honeypot hierarchy alert",
                    member_identity=member_identity,
                    action="ban",
                    detail="Discord rejected the ban, likely because the member is above the bot in the role hierarchy.",
                )
            return False
        except discord.HTTPException as exc:
            await self._log_alert(
                guild,
                title="Honeypot ban failure",
                member_identity=member_identity,
                action="ban",
                detail=str(exc),
            )
            return False

        embed = self._base_log_embed("Honeypot ban", discord.Color.red(), member_identity)
        embed.add_field(name="Tenure", value=f"{tenure_days:.2f} days", inline=True)
        embed.add_field(name="DM delivered", value=str(dm_delivered), inline=True)
        self._add_message_fields(embed, captured_content, attachment_names)
        await self._log_embed(guild, embed)
        return True

    async def _quarantine_member(
        self,
        guild: discord.Guild,
        member: discord.Member,
        member_identity: str,
        captured_content: str,
        attachment_names: tuple[str, ...],
        existing_record: dict[str, Any] | None,
    ) -> bool:
        keep, current_snapshot = self._partition_roles(member)
        if existing_record is not None and existing_record.get("state") in {"pending", "failed"}:
            stored_roles = existing_record.get("roles")
            snapshot = (
                [role_id for role_id in stored_roles if isinstance(role_id, int)]
                if isinstance(stored_roles, list)
                else []
            )
        else:
            snapshot = current_snapshot

        await self._write_pending_record(guild, member.id, snapshot)
        timeout_until = discord.utils.utcnow() + timedelta(days=TIMEOUT_DAYS)
        try:
            await member.edit(roles=keep, timed_out_until=timeout_until, reason=ENFORCEMENT_REASON)
        except discord.NotFound as exc:
            await self._mark_failed(guild, member.id, str(exc))
            await self._log_alert(
                guild,
                title="Honeypot quarantine abandoned",
                member_identity=member_identity,
                action="quarantine",
                detail="The member left before quarantine could be applied.",
            )
            return False
        except discord.Forbidden as exc:
            await self._mark_failed(guild, member.id, str(exc))
            bot_member = guild.me
            missing_permissions: list[str] = []
            if bot_member is not None:
                if not bot_member.guild_permissions.manage_roles:
                    missing_permissions.append("manage_roles")
                if not bot_member.guild_permissions.moderate_members:
                    missing_permissions.append("moderate_members")
            if missing_permissions:
                for permission in missing_permissions:
                    await self._log_permission_failure(guild, member_identity, "quarantine", permission)
            else:
                await self._log_alert(
                    guild,
                    title="Honeypot hierarchy alert",
                    member_identity=member_identity,
                    action="quarantine",
                    detail="Discord rejected the quarantine, likely because the member is above the bot in the hierarchy.",
                )
            return False
        except discord.HTTPException as exc:
            await self._mark_failed(guild, member.id, str(exc))
            await self._log_alert(
                guild,
                title="Honeypot quarantine failure",
                member_identity=member_identity,
                action="quarantine",
                detail=str(exc),
            )
            return False

        await self._mark_completed(guild, member.id)
        dm_delivered = await self._send_dm(member, QUARANTINE_NOTICE)
        embed = self._base_log_embed("Honeypot quarantine", discord.Color.orange(), member_identity)
        embed.add_field(name="Roles stripped", value=str(len(current_snapshot)), inline=True)
        embed.add_field(name="Timeout expires", value=discord.utils.format_dt(timeout_until), inline=True)
        embed.add_field(name="DM delivered", value=str(dm_delivered), inline=True)
        if not current_snapshot:
            embed.add_field(name="Role outcome", value="No assignable roles were present.", inline=False)
        self._add_message_fields(embed, captured_content, attachment_names)
        await self._log_embed(guild, embed)
        return True

    @staticmethod
    def _partition_roles(member: discord.Member) -> tuple[list[discord.Role], list[int]]:
        keep: list[discord.Role] = []
        snapshot: list[int] = []
        for role in member.roles:
            if role.is_default():
                # @everyone is implicit and must never appear in a member roles payload.
                continue
            if role.is_assignable():
                snapshot.append(role.id)
            else:
                keep.append(role)
        return keep, snapshot

    async def _write_pending_record(self, guild: discord.Guild, user_id: int, role_ids: list[int]) -> None:
        now = datetime.now(UTC).isoformat()
        current = await self.config.guild(guild).quarantined_users()
        if not isinstance(current, dict):
            log.error("Malformed quarantine store in guild %s; replacing it", guild.id)
            await self.config.guild(guild).quarantined_users.set({})
        async with self.config.guild(guild).quarantined_users() as records:
            previous = records.get(str(user_id))
            quarantined_at = previous.get("quarantined_at", now) if isinstance(previous, dict) else now
            records[str(user_id)] = {
                "roles": list(role_ids),
                "quarantined_at": quarantined_at,
                "state": "pending",
            }

    async def _mark_completed(self, guild: discord.Guild, user_id: int) -> None:
        async with self.config.guild(guild).quarantined_users() as records:
            if not isinstance(records, dict):
                return
            record = records.get(str(user_id))
            if isinstance(record, dict):
                record["state"] = "completed"
                record["completed_at"] = datetime.now(UTC).isoformat()
                record.pop("last_error", None)
                records[str(user_id)] = record

    async def _mark_failed(self, guild: discord.Guild, user_id: int, error: str) -> None:
        async with self.config.guild(guild).quarantined_users() as records:
            if not isinstance(records, dict):
                return
            record = records.get(str(user_id))
            if isinstance(record, dict):
                record["state"] = "failed"
                record["last_error"] = error[:500]
                records[str(user_id)] = record

    @staticmethod
    async def _send_dm(member: discord.Member, message: str) -> bool:
        try:
            await member.send(message)
        except (discord.Forbidden, discord.HTTPException):
            return False
        return True

    @staticmethod
    def _base_log_embed(title: str, color: discord.Color, member_identity: str) -> discord.Embed:
        embed = discord.Embed(title=title, color=color, timestamp=datetime.now(UTC))
        embed.add_field(name="Member", value=Honeypot._field_value(member_identity), inline=False)
        return embed

    @staticmethod
    def _field_value(value: str) -> str:
        value = value or "(none)"
        if len(value) <= EMBED_FIELD_LIMIT:
            return value
        return f"{value[: EMBED_FIELD_LIMIT - 1]}…"

    def _add_message_fields(self, embed: discord.Embed, content: str, attachment_names: tuple[str, ...]) -> None:
        attachments = ", ".join(attachment_names) if attachment_names else "(none)"
        embed.add_field(name="Message content", value=self._field_value(content or "(no text)"), inline=False)
        embed.add_field(name="Attachments", value=self._field_value(attachments), inline=False)

    async def _log_embed(self, guild: discord.Guild, embed: discord.Embed) -> None:
        channel = guild.get_channel(LOG_CHANNEL_ID)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            log.error("Honeypot log channel %s is unavailable in guild %s", LOG_CHANNEL_ID, guild.id)
            return
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException) as exc:
            log.error(
                "Could not send honeypot log to channel %s in guild %s: %s",
                LOG_CHANNEL_ID,
                guild.id,
                exc,
            )

    async def _log_alert(
        self,
        guild: discord.Guild,
        *,
        title: str,
        member_identity: str,
        action: str,
        detail: str,
    ) -> None:
        embed = self._base_log_embed(title, discord.Color.red(), member_identity)
        embed.add_field(name="Attempted action", value=self._field_value(action), inline=True)
        embed.add_field(name="Details", value=self._field_value(detail), inline=False)
        await self._log_embed(guild, embed)

    async def _log_permission_failure(
        self, guild: discord.Guild, member_identity: str, action: str, permission: str
    ) -> None:
        await self._log_alert(
            guild,
            title="Honeypot missing permission",
            member_identity=member_identity,
            action=action,
            detail=f"The bot is missing `{permission}`.",
        )

    @commands.hybrid_group(name="honeypot")
    @commands.guild_only()
    @commands.check(_staff_or_admin)
    async def honeypot_group(self, ctx: commands.Context) -> None:
        """Inspect, restore, or clear honeypot quarantine records."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help()

    @honeypot_group.command(name="restore")
    async def honeypot_restore(self, ctx: commands.Context, member: discord.Member) -> None:
        """Restore a member's held roles and clear their timeout."""
        guild = ctx.guild
        if guild is None:
            return
        records = await self.config.guild(guild).quarantined_users()
        record = records.get(str(member.id)) if isinstance(records, dict) else None
        if not isinstance(record, dict):
            await ctx.send(f"{member.mention} has no honeypot quarantine record.")
            return
        stored_roles = record.get("roles")
        if not isinstance(stored_roles, list):
            await ctx.send(f"{member.mention}'s quarantine record is malformed; no changes were made.")
            return

        # @everyone is implicit and must never appear in a member roles payload.
        final_roles = [role for role in member.roles if not role.is_default()]
        final_ids = {role.id for role in final_roles}
        unrestorable = 0
        for role_id in stored_roles:
            if not isinstance(role_id, int):
                unrestorable += 1
                continue
            if role_id in final_ids:
                continue
            role = guild.get_role(role_id)
            if role is None or not role.is_assignable():
                unrestorable += 1
                continue
            final_roles.append(role)
            final_ids.add(role.id)

        try:
            await member.edit(
                roles=final_roles,
                timed_out_until=None,
                reason=f"Honeypot restore requested by {ctx.author} ({ctx.author.id})",
            )
        except discord.Forbidden:
            await ctx.send(
                f"Could not restore {member.mention}; check the bot's permissions and role hierarchy. "
                "The quarantine record was retained."
            )
            return
        except discord.HTTPException as exc:
            await ctx.send(f"Could not restore {member.mention}: {exc}. The quarantine record was retained.")
            return

        async with self.config.guild(guild).quarantined_users() as stored:
            if isinstance(stored, dict):
                stored.pop(str(member.id), None)
        self._enforced_users.discard((guild.id, member.id))
        await ctx.send(f"Restored {member.mention}; {unrestorable} role(s) could not be reapplied.")

        embed = self._base_log_embed("Honeypot restore", discord.Color.green(), f"{member} ({member.id})")
        embed.add_field(name="Restored by", value=self._field_value(f"{ctx.author} ({ctx.author.id})"), inline=False)
        embed.add_field(name="Unrestorable roles", value=str(unrestorable), inline=True)
        await self._log_embed(guild, embed)

    @honeypot_group.command(name="list")
    async def honeypot_list(self, ctx: commands.Context) -> None:
        """List current honeypot quarantine records."""
        guild = ctx.guild
        if guild is None:
            return
        records = await self.config.guild(guild).quarantined_users()
        if not isinstance(records, dict) or not records:
            await ctx.send("There are no honeypot quarantine records.")
            return
        lines = ["Honeypot quarantine records:"]
        for user_id, record in records.items():
            if not isinstance(record, dict):
                lines.append(f"- `{user_id}` — malformed record")
                continue
            member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
            member_label = member.mention if member is not None else f"Unknown member `{user_id}`"
            state = record.get("state", "completed")
            timestamp = record.get("quarantined_at", "unknown time")
            roles = record.get("roles", [])
            role_count = len(roles) if isinstance(roles, list) else 0
            lines.append(f"- {member_label} — {state}, {timestamp}, {role_count} stored role(s)")
        for page in pagify("\n".join(lines), page_length=1900):
            await ctx.send(page)

    @honeypot_group.command(name="clear")
    async def honeypot_clear(self, ctx: commands.Context, member: discord.Member) -> None:
        """Delete a quarantine record without changing roles or timeout."""
        guild = ctx.guild
        if guild is None:
            return
        removed = False
        async with self.config.guild(guild).quarantined_users() as records:
            if isinstance(records, dict) and str(member.id) in records:
                records.pop(str(member.id), None)
                removed = True
        if not removed:
            await ctx.send(f"{member.mention} has no honeypot quarantine record.")
            return
        self._enforced_users.discard((guild.id, member.id))
        await ctx.send(f"Cleared {member.mention}'s quarantine record without changing roles or timeout.")
