"""Audit log event handling for the AntiNuke cog."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

import discord
from redbot.core import Config
from redbot.core.bot import Red

from .actions import QuarantineActions
from .constants import DANGEROUS_PERMISSIONS
from .utils import ActionCache, has_dangerous_permission

log = logging.getLogger("red.kirin-cogs.antinuke.events")

# Audit log actions that map straight onto a monitored action type.
AUDIT_ACTION_TYPES: dict[discord.AuditLogAction, str] = {
    discord.AuditLogAction.channel_create: "channel_create",
    discord.AuditLogAction.channel_delete: "channel_delete",
    discord.AuditLogAction.role_create: "role_create",
    discord.AuditLogAction.role_delete: "role_delete",
    discord.AuditLogAction.ban: "ban",
    discord.AuditLogAction.kick: "kick",
    discord.AuditLogAction.member_prune: "guild_prune",
    discord.AuditLogAction.webhook_create: "webhook_create",
    discord.AuditLogAction.webhook_delete: "webhook_delete",
    discord.AuditLogAction.bot_add: "bot_add",
}


class EventHandlers:
    """Attributes monitored audit log entries to their actor and enforces thresholds."""

    def __init__(
        self,
        bot: Red,
        config: Config,
        action_cache: ActionCache,
        quarantine_actions: QuarantineActions,
    ) -> None:
        self.bot = bot
        self.config = config
        self.action_cache = action_cache
        self.quarantine_actions = quarantine_actions
        self._background_tasks: set[asyncio.Task[Any]] = set()

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
            log.error("AntiNuke enforcement task failed: %s", exc, exc_info=exc)

    async def cancel_all_tasks(self) -> None:
        """Cancel and gather every outstanding enforcement task (unload path)."""
        tasks = list(self._background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()

    async def is_enabled(self, guild: discord.Guild) -> bool:
        """Check if AntiNuke is enabled for the guild."""
        return await self.config.guild(guild).enabled()

    async def is_trusted(self, guild: discord.Guild, user: discord.Member) -> bool:
        """Check if a user is trusted (bypasses AntiNuke)."""
        # Server owner is always trusted
        if guild.owner_id == user.id:
            return True

        # Check trusted users
        trusted_users = await self.config.guild(guild).trusted_users()
        if user.id in trusted_users:
            return True

        # Check trusted roles
        trusted_roles = await self.config.guild(guild).trusted_roles()
        user_role_ids = [role.id for role in user.roles]
        return bool(any(role_id in trusted_roles for role_id in user_role_ids))

    @staticmethod
    def classify(entry: discord.AuditLogEntry, monitor: dict) -> str | None:
        """Return the monitored action type an audit log entry represents, if any."""
        if action_type := AUDIT_ACTION_TYPES.get(entry.action):
            return action_type

        if entry.action == discord.AuditLogAction.role_update:
            after = getattr(entry.after, "permissions", None)
            if after is None:
                return None
            before = getattr(entry.before, "permissions", None) or discord.Permissions.none()
            dangerous_perms = monitor.get("dangerous_permission_add", {}).get("permissions", DANGEROUS_PERMISSIONS)
            if has_dangerous_permission(before, after, dangerous_perms):
                return "dangerous_permission_add"
            return None

        if entry.action == discord.AuditLogAction.guild_update and hasattr(entry.after, "vanity_url_code"):
            return "vanity_change"

        return None

    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        """Count a monitored action against its actor and enforce the threshold."""
        guild = entry.guild
        if entry.user_id is None or not await self.is_enabled(guild):
            return

        monitor = await self.config.guild(guild).monitor()
        action_type = self.classify(entry, monitor)
        if action_type is None:
            return

        monitor_config = monitor.get(action_type, {})
        if not monitor_config.get("enabled", True):
            return

        # This bot's own actions (moderation commands, AntiNuke kicks) are never attributed to it.
        if entry.user_id == guild.me.id:
            return

        culprit = guild.get_member(entry.user_id)
        if culprit is None or await self.is_trusted(guild, culprit):
            return

        threshold = monitor_config.get("threshold", 2)
        timeframe = monitor_config.get("timeframe", 60)
        count = self.action_cache.record_action(guild.id, culprit.id, action_type, timeframe)
        if count < threshold:
            return

        if culprit.bot:
            # A bot's permissions live on its managed role, which quarantine cannot strip, so remove it.
            self._create_task(self.quarantine_actions.remove_bot(guild, culprit, action_type, self.action_cache))
        else:
            self._create_task(
                self.quarantine_actions.execute_quarantine(guild, culprit, action_type, self.action_cache)
            )

        target_id = getattr(entry.target, "id", None)
        if action_type == "bot_add" and monitor_config.get("kick_bot", True) and isinstance(target_id, int):
            added_bot = guild.get_member(target_id) or discord.Object(id=target_id)
            self._create_task(self.quarantine_actions.kick_bot(guild, added_bot))
