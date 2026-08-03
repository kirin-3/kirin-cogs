"""Quarantine, restore, and notification actions for the AntiNuke cog."""

import asyncio
import datetime
import logging
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import discord
from redbot.core import Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import bold

from .constants import ACTION_NAMES
from .utils import is_above_in_hierarchy

log = logging.getLogger("red.kirin-cogs.antinuke.actions")


@dataclass
class _LockEntry:
    """A keyed asyncio lock plus the number of coroutines holding or awaiting it."""

    lock: asyncio.Lock
    holders: int = 0


class QuarantineActions:
    """Handles quarantine, restore, and notification actions."""

    def __init__(self, bot: Red, config: Config) -> None:
        self.bot = bot
        self.config = config
        self._background_tasks: set[asyncio.Task[Any]] = set()
        # Per-(guild, member) quarantine locks; idle entries are removed.
        self._quarantine_locks: dict[tuple[int, int], _LockEntry] = {}

    @asynccontextmanager
    async def _quarantine_lock(self, guild_id: int, user_id: int) -> AsyncGenerator[asyncio.Lock, None]:
        """Serialize quarantine operations for one guild member.

        Registry entries are removed once no coroutine holds or awaits them,
        so the registry cannot grow unboundedly.
        """
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

    def _create_task(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        """Release the task and retrieve/log any exception it raised."""
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("AntiNuke action task failed: %s", exc, exc_info=exc)

    async def cancel_all_tasks(self) -> None:
        """Cancel and gather every outstanding background task (unload path)."""
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()
        self._quarantine_locks.clear()

    async def execute_quarantine(
        self,
        guild: discord.Guild,
        user: discord.Member,
        trigger_action: str,
        action_cache=None,
    ) -> bool:
        """
        Atomically quarantine a user with a single API call.

        Quarantine transitions are serialized per guild member and modeled as
        explicit states: the original-role snapshot is persisted as ``pending``
        before the Discord edit, marked ``completed`` only after the edit
        succeeds, and marked ``failed`` (retaining the snapshot for a safe
        retry) when Discord rejects the edit. The first valid snapshot is
        never replaced by quarantine-state roles.

        Parameters
        ----------
        guild : discord.Guild
            The guild where quarantine is being executed.
        user : discord.Member
            The user to quarantine.
        trigger_action : str
            The action that triggered the quarantine.
        action_cache : Optional[ActionCache]
            The action cache to clear after quarantine.

        Returns
        -------
        bool
            True if successful (or already quarantined), False otherwise.
        """
        # Get bot's member object
        bot_member = guild.me

        # Hierarchy check - CRITICAL
        if not is_above_in_hierarchy(bot_member, user):
            await self.notify_owner_hierarchy_issue(guild, user, trigger_action)
            return False

        # Get quarantine role
        quarantine_role_id = await self.config.guild(guild).quarantine_role()
        if not quarantine_role_id:
            log.warning(f"Quarantine attempted in guild {guild.id} but no quarantine role is set")
            return False

        quarantine_role = guild.get_role(quarantine_role_id)
        if not quarantine_role:
            log.warning(f"Quarantine role {quarantine_role_id} not found in guild {guild.id}")
            return False

        # Check hierarchy for quarantine role
        if bot_member.top_role <= quarantine_role:
            log.warning(f"Quarantine role is above bot's top role in guild {guild.id}")
            return False

        async with self._quarantine_lock(guild.id, user.id):
            existing_users = await self.config.guild(guild).quarantined_users()
            existing = existing_users.get(str(user.id)) if isinstance(existing_users, dict) else None

            if isinstance(existing, dict):
                # Records without a state predate the state model: those users
                # are already quarantined, so preserve the first snapshot.
                state = existing.get("state", "completed")
                if state == "completed":
                    log.debug(f"User {user.id} in guild {guild.id} is already quarantined")
                    return True
                # pending/failed: safe retry reusing the FIRST snapshot — never
                # re-capture roles from a member already wearing quarantine.
                role_ids = [rid for rid in existing.get("roles", []) if isinstance(rid, int)]
            else:
                # First quarantine: capture the original manageable roles now.
                role_ids = [role.id for role in user.roles if role != guild.default_role]

            now_iso = datetime.datetime.now(datetime.UTC).isoformat()
            quarantine_data = {
                "roles": role_ids,
                "reason": f"AntiNuke triggered: {trigger_action}",
                "quarantined_by": "anti-nuke",
                "quarantined_at": now_iso,
                "trigger_action": trigger_action,
                "state": "pending",
            }

            # Persist the pending transition BEFORE the Discord effect.
            async with self.config.guild(guild).quarantined_users() as q_users:
                q_users[str(user.id)] = quarantine_data

            try:
                # SINGLE API CALL - Atomic role replacement
                await user.edit(
                    roles=[quarantine_role],
                    reason=f"AntiNuke: {ACTION_NAMES.get(trigger_action, trigger_action)} threshold exceeded",
                )
            except discord.Forbidden:
                await self._mark_quarantine_failed(guild, user.id, "forbidden")
                # Still notify owner even after hierarchy check (race condition)
                await self.notify_owner_hierarchy_issue(guild, user, trigger_action)
                return False
            except discord.HTTPException as e:
                await self._mark_quarantine_failed(guild, user.id, str(e)[:200])
                log.error(f"Failed to quarantine user {user.id} in guild {guild.id}: {e}")
                return False

            # Finalize only after Discord success.
            async with self.config.guild(guild).quarantined_users() as q_users:
                record = q_users.get(str(user.id))
                if isinstance(record, dict):
                    record["state"] = "completed"
                    record["completed_at"] = datetime.datetime.now(datetime.UTC).isoformat()
                    q_users[str(user.id)] = record

            # Clear action cache for this user
            if action_cache:
                action_cache.clear_user(guild.id, user.id)

            # Log the action (non-blocking), counting roles stripped from the
            # preserved pre-edit snapshot that the bot can actually manage.
            stripped_count = self._stripped_count(guild, bot_member, role_ids)
            self._create_task(self.log_quarantine(guild, user, trigger_action, stripped_count))

            return True

    @staticmethod
    def _stripped_count(guild: discord.Guild, bot_member: discord.Member, role_ids: list[int]) -> int:
        """Count preserved snapshot roles the bot could actually strip."""
        count = 0
        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role is not None and bot_member.top_role > role:
                count += 1
        return count

    async def _mark_quarantine_failed(self, guild: discord.Guild, user_id: int, error: str) -> None:
        """Mark a pending quarantine as failed, retaining its snapshot for retry."""
        async with self.config.guild(guild).quarantined_users() as q_users:
            record = q_users.get(str(user_id))
            if isinstance(record, dict):
                record["state"] = "failed"
                record["last_error"] = error
                q_users[str(user_id)] = record

    async def restore_user(self, guild: discord.Guild, user: discord.Member, restored_by: str = "manual") -> bool:
        """
        Restore a quarantined user's roles.

        Parameters
        ----------
        guild : discord.Guild
            The guild where restoration is happening.
        user : discord.Member
            The user to restore.
        restored_by : str
            Who or what initiated the restoration.

        Returns
        -------
        bool
            True if successful, False otherwise.
        """
        # Get stored quarantine data
        q_users = await self.config.guild(guild).quarantined_users()
        user_data = q_users.get(str(user.id))

        if not user_data:
            return False

        # Get role objects for stored role IDs
        roles_to_restore: list[discord.Role] = []
        missing_roles: list[int] = []

        for role_id in user_data.get("roles", []):
            role = guild.get_role(role_id)
            if role:
                # Check if bot can assign this role
                if guild.me.top_role > role:
                    roles_to_restore.append(role)
                else:
                    log.warning(f"Cannot restore role {role_id} to user {user.id}: role is above bot's top role")
            else:
                missing_roles.append(role_id)

        # Remove quarantine role if present
        quarantine_role_id = await self.config.guild(guild).quarantine_role()
        quarantine_role = guild.get_role(quarantine_role_id) if quarantine_role_id else None

        try:
            # Build final role list
            final_roles = roles_to_restore.copy()

            # Add back any roles the user should have (excluding quarantine)
            for role in user.roles:
                if role != guild.default_role and role != quarantine_role and role not in final_roles:
                    final_roles.append(role)

            # Restore roles
            await user.edit(
                roles=final_roles,
                reason=f"AntiNuke: User unquaranted by {restored_by}",
            )

            # Remove from quarantine storage
            async with self.config.guild(guild).quarantined_users() as q_users:
                if str(user.id) in q_users:
                    del q_users[str(user.id)]

            # Log restoration
            self._create_task(self.log_restoration(guild, user, restored_by, missing_roles))

            return True

        except discord.Forbidden:
            log.error(f"Failed to restore user {user.id} in guild {guild.id}: missing permissions")
            return False
        except discord.HTTPException as e:
            log.error(f"Failed to restore user {user.id} in guild {guild.id}: {e}")
            return False

    async def kick_bot(self, guild: discord.Guild, bot_user: discord.Member) -> bool:
        """
        Kick a bot from the guild.

        Parameters
        ----------
        guild : discord.Guild
            The guild to kick the bot from.
        bot_user : discord.Member
            The bot member to kick.

        Returns
        -------
        bool
            True if successful, False otherwise.
        """
        try:
            await guild.kick(
                bot_user,
                reason="AntiNuke: Unauthorized bot addition",
            )
            return True
        except discord.Forbidden:
            log.warning(f"Failed to kick bot {bot_user.id} in guild {guild.id}: missing permissions")
            return False
        except discord.HTTPException as e:
            log.error(f"Failed to kick bot {bot_user.id} in guild {guild.id}: {e}")
            return False

    async def log_quarantine(
        self,
        guild: discord.Guild,
        user: discord.Member,
        trigger_action: str,
        stripped_count: int | None = None,
    ) -> None:
        """
        Log a quarantine action to the designated log channel.

        Parameters
        ----------
        guild : discord.Guild
            The guild where the quarantine occurred.
        user : discord.Member
            The user who was quarantined.
        trigger_action : str
            The action that triggered the quarantine.
        stripped_count : Optional[int]
            Number of roles stripped, calculated from the preserved pre-edit
            role set. Falls back to the member's current roles when omitted.
        """
        log_channel_id = await self.config.guild(guild).log_channel()
        if not log_channel_id:
            return

        log_channel = guild.get_channel(log_channel_id)
        if not isinstance(log_channel, discord.TextChannel):
            return

        action_name = ACTION_NAMES.get(trigger_action, trigger_action)

        embed = discord.Embed(
            title="🛡️ AntiNuke Quarantine",
            description=f"{user.mention} has been quarantined.",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.UTC),
        )

        embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        embed.add_field(name="Trigger", value=bold(action_name), inline=True)
        embed.add_field(
            name="Roles Stripped",
            value=str(stripped_count if stripped_count is not None else len(user.roles) - 1),
            inline=True,
        )

        embed.set_footer(text=f"Guild: {guild.name}")

        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            log.warning(f"Cannot send to log channel {log_channel_id} in guild {guild.id}")

    async def log_restoration(
        self,
        guild: discord.Guild,
        user: discord.Member,
        restored_by: str,
        missing_roles: list[int],
    ) -> None:
        """
        Log a restoration action to the designated log channel.

        Parameters
        ----------
        guild : discord.Guild
            The guild where the restoration occurred.
        user : discord.Member
            The user who was restored.
        restored_by : str
            Who or what initiated the restoration.
        missing_roles : List[int]
            List of role IDs that could not be restored.
        """
        log_channel_id = await self.config.guild(guild).log_channel()
        if not log_channel_id:
            return

        log_channel = guild.get_channel(log_channel_id)
        if not isinstance(log_channel, discord.TextChannel):
            return

        embed = discord.Embed(
            title="✅ AntiNuke Restoration",
            description=f"{user.mention} has been unquarantined.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.UTC),
        )

        embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        embed.add_field(name="Restored By", value=bold(restored_by), inline=True)

        if missing_roles:
            embed.add_field(
                name="Missing Roles",
                value=f"{len(missing_roles)} role(s) could not be restored (deleted or missing)",
                inline=False,
            )

        embed.set_footer(text=f"Guild: {guild.name}")

        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            log.warning(f"Cannot send to log channel {log_channel_id} in guild {guild.id}")

    async def notify_owner_hierarchy_issue(
        self,
        guild: discord.Guild,
        user: discord.Member,
        trigger_action: str,
    ) -> None:
        """
        Notify the server owner about a hierarchy issue preventing quarantine.

        Parameters
        ----------
        guild : discord.Guild
            The guild where the issue occurred.
        user : discord.Member
            The user who could not be quarantined.
        trigger_action : str
            The action that triggered the quarantine attempt.
        """
        action_name = ACTION_NAMES.get(trigger_action, trigger_action)

        # Try log channel first
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if isinstance(log_channel, discord.TextChannel):
                embed = discord.Embed(
                    title="⚠️ AntiNuke Hierarchy Issue",
                    description=f"Cannot quarantine {user.mention} - they have equal or higher roles than the bot.",
                    color=discord.Color.orange(),
                    timestamp=datetime.datetime.now(datetime.UTC),
                )

                embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
                embed.add_field(name="Trigger", value=bold(action_name), inline=True)
                embed.add_field(
                    name="Action Required",
                    value="Move the bot's role above this user's highest role to enable quarantine.",
                    inline=False,
                )

                try:
                    await log_channel.send(embed=embed)
                    return
                except discord.Forbidden:
                    pass

        # DM the owner as fallback
        owner = guild.owner
        if owner:
            try:
                embed = discord.Embed(
                    title="⚠️ AntiNuke Alert - Action Required",
                    description=f"In **{guild.name}**, AntiNuke detected suspicious activity but could not act.",
                    color=discord.Color.orange(),
                )

                embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
                embed.add_field(name="Trigger", value=bold(action_name), inline=True)
                embed.add_field(
                    name="Issue",
                    value="User has equal or higher roles than the bot.",
                    inline=False,
                )
                embed.add_field(
                    name="Solution",
                    value="Move the bot's role above this user's highest role.",
                    inline=False,
                )

                await owner.send(embed=embed)
            except discord.Forbidden:
                log.warning(f"Cannot DM owner {owner.id} about hierarchy issue in guild {guild.id}")

    async def notify_owner_missing_permissions(self, guild: discord.Guild, permission: str) -> None:
        """
        Notify the server owner about missing permissions.

        Parameters
        ----------
        guild : discord.Guild
            The guild where permissions are missing.
        permission : str
            The missing permission name.
        """
        # Try log channel first
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if isinstance(log_channel, discord.TextChannel):
                try:
                    await log_channel.send(
                        f"⚠️ AntiNuke is missing the `{permission}` permission. Some features may not work correctly."
                    )
                    return
                except discord.Forbidden:
                    pass

        # DM the owner as fallback
        owner = guild.owner
        if owner:
            try:
                await owner.send(
                    f"⚠️ **AntiNuke Alert** in **{guild.name}**\n\n"
                    f"AntiNuke is missing the `{permission}` permission. "
                    "Some features may not work correctly."
                )
            except discord.Forbidden:
                log.warning(f"Cannot DM owner {owner.id} about missing permissions in guild {guild.id}")
