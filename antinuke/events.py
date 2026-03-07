"""Gateway event handlers for the AntiNuke cog."""

import asyncio
import logging

import discord
from redbot.core import Config
from redbot.core.bot import Red

from .actions import QuarantineActions
from .audit import AuditLogHelper
from .constants import DANGEROUS_PERMISSIONS
from .utils import ActionCache, has_dangerous_permission

log = logging.getLogger("red.kirin-cogs.antinuke.events")


class EventHandlers:
    """Handles Discord gateway events for AntiNuke monitoring."""

    def __init__(
        self,
        bot: Red,
        config: Config,
        action_cache: ActionCache,
        audit_helper: AuditLogHelper,
        quarantine_actions: QuarantineActions,
    ) -> None:
        self.bot = bot
        self.config = config
        self.action_cache = action_cache
        self.audit_helper = audit_helper
        self.quarantine_actions = quarantine_actions

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
        if any(role_id in trusted_roles for role_id in user_role_ids):
            return True

        return False

    async def get_monitor_config(self, guild: discord.Guild, action_type: str) -> dict:
        """Get monitor configuration for an action type."""
        monitor = await self.config.guild(guild).monitor()
        return monitor.get(action_type, {})

    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Handle channel deletion events."""
        guild = channel.guild

        if not await self.is_enabled(guild):
            return

        monitor_config = await self.get_monitor_config(guild, "channel_delete")
        if not monitor_config.get("enabled", True):
            return

        threshold = monitor_config.get("threshold", 2)
        timeframe = monitor_config.get("timeframe", 60)

        # Record action with unknown actor (0)
        count = self.action_cache.record_action(guild.id, 0, "channel_delete", timeframe)

        # Check if threshold hit
        if count >= threshold:
            # Fetch audit logs to find culprits
            asyncio.create_task(self._investigate_channel_deletion(guild, monitor_config))

    async def _investigate_channel_deletion(self, guild: discord.Guild, config: dict) -> None:
        """Investigate channel deletion and quarantine culprits."""
        threshold = config.get("threshold", 2)
        timeframe = config.get("timeframe", 60)

        culprits = await self.audit_helper.get_channel_delete_culprit(guild, timeframe, threshold)

        for culprit, count in culprits:
            if await self.is_trusted(guild, culprit):
                continue

            asyncio.create_task(
                self.quarantine_actions.execute_quarantine(guild, culprit, "channel_delete", self.action_cache)
            )

    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Handle channel creation events."""
        guild = channel.guild

        if not await self.is_enabled(guild):
            return

        monitor_config = await self.get_monitor_config(guild, "channel_create")
        if not monitor_config.get("enabled", True):
            return

        threshold = monitor_config.get("threshold", 3)
        timeframe = monitor_config.get("timeframe", 60)

        # Record action with unknown actor
        count = self.action_cache.record_action(guild.id, 0, "channel_create", timeframe)

        if count >= threshold:
            asyncio.create_task(self._investigate_channel_creation(guild, monitor_config))

    async def _investigate_channel_creation(self, guild: discord.Guild, config: dict) -> None:
        """Investigate channel creation and quarantine culprits."""
        threshold = config.get("threshold", 3)
        timeframe = config.get("timeframe", 60)

        culprits = await self.audit_helper.get_channel_create_culprit(guild, timeframe, threshold)

        for culprit, count in culprits:
            if await self.is_trusted(guild, culprit):
                continue

            asyncio.create_task(
                self.quarantine_actions.execute_quarantine(guild, culprit, "channel_create", self.action_cache)
            )

    async def on_guild_role_delete(self, role: discord.Role) -> None:
        """Handle role deletion events."""
        guild = role.guild

        if not await self.is_enabled(guild):
            return

        monitor_config = await self.get_monitor_config(guild, "role_delete")
        if not monitor_config.get("enabled", True):
            return

        threshold = monitor_config.get("threshold", 2)
        timeframe = monitor_config.get("timeframe", 60)

        count = self.action_cache.record_action(guild.id, 0, "role_delete", timeframe)

        if count >= threshold:
            asyncio.create_task(self._investigate_role_deletion(guild, monitor_config))

    async def _investigate_role_deletion(self, guild: discord.Guild, config: dict) -> None:
        """Investigate role deletion and quarantine culprits."""
        threshold = config.get("threshold", 2)
        timeframe = config.get("timeframe", 60)

        culprits = await self.audit_helper.get_role_delete_culprit(guild, timeframe, threshold)

        for culprit, count in culprits:
            if await self.is_trusted(guild, culprit):
                continue

            asyncio.create_task(
                self.quarantine_actions.execute_quarantine(guild, culprit, "role_delete", self.action_cache)
            )

    async def on_guild_role_create(self, role: discord.Role) -> None:
        """Handle role creation events."""
        guild = role.guild

        if not await self.is_enabled(guild):
            return

        monitor_config = await self.get_monitor_config(guild, "role_create")
        if not monitor_config.get("enabled", True):
            return

        threshold = monitor_config.get("threshold", 3)
        timeframe = monitor_config.get("timeframe", 60)

        count = self.action_cache.record_action(guild.id, 0, "role_create", timeframe)

        if count >= threshold:
            asyncio.create_task(self._investigate_role_creation(guild, monitor_config))

    async def _investigate_role_creation(self, guild: discord.Guild, config: dict) -> None:
        """Investigate role creation and quarantine culprits."""
        threshold = config.get("threshold", 3)
        timeframe = config.get("timeframe", 60)

        culprits = await self.audit_helper.get_role_create_culprit(guild, timeframe, threshold)

        for culprit, count in culprits:
            if await self.is_trusted(guild, culprit):
                continue

            asyncio.create_task(
                self.quarantine_actions.execute_quarantine(guild, culprit, "role_create", self.action_cache)
            )

    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        """Handle role update events - check for dangerous permission additions."""
        guild = before.guild

        if not await self.is_enabled(guild):
            return

        monitor_config = await self.get_monitor_config(guild, "dangerous_permission_add")
        if not monitor_config.get("enabled", True):
            return

        # Get configured dangerous permissions
        dangerous_perms = monitor_config.get("permissions", DANGEROUS_PERMISSIONS)

        # Check if dangerous permission was added
        added_perm = has_dangerous_permission(before.permissions, after.permissions, dangerous_perms)

        if added_perm:
            # This is an instant action (threshold 1)
            asyncio.create_task(self._investigate_role_permission_change(guild, after.id, monitor_config, added_perm))

    async def _investigate_role_permission_change(
        self, guild: discord.Guild, role_id: int, config: dict, perm_name: str
    ) -> None:
        """Investigate role permission change and quarantine culprit."""
        timeframe = config.get("timeframe", 60)

        result = await self.audit_helper.get_role_update_culprit(
            guild, role_id, timeframe, config.get("permissions", DANGEROUS_PERMISSIONS)
        )

        if result:
            culprit, added_perm = result
            if not await self.is_trusted(guild, culprit):
                asyncio.create_task(
                    self.quarantine_actions.execute_quarantine(
                        guild, culprit, "dangerous_permission_add", self.action_cache
                    )
                )

    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        """Handle member ban events."""
        if not await self.is_enabled(guild):
            return

        monitor_config = await self.get_monitor_config(guild, "ban")
        if not monitor_config.get("enabled", True):
            return

        threshold = monitor_config.get("threshold", 3)
        timeframe = monitor_config.get("timeframe", 120)

        count = self.action_cache.record_action(guild.id, 0, "ban", timeframe)

        if count >= threshold:
            asyncio.create_task(self._investigate_bans(guild, monitor_config))

    async def _investigate_bans(self, guild: discord.Guild, config: dict) -> None:
        """Investigate mass bans and quarantine culprits."""
        threshold = config.get("threshold", 3)
        timeframe = config.get("timeframe", 120)

        culprits = await self.audit_helper.get_ban_culprit(guild, timeframe, threshold)

        for culprit, count in culprits:
            if await self.is_trusted(guild, culprit):
                continue

            asyncio.create_task(self.quarantine_actions.execute_quarantine(guild, culprit, "ban", self.action_cache))

    async def on_member_remove(self, member: discord.Member) -> None:
        """Handle member remove events - detect kicks."""
        guild = member.guild

        if not await self.is_enabled(guild):
            return

        monitor_config = await self.get_monitor_config(guild, "kick")
        if not monitor_config.get("enabled", True):
            return

        threshold = monitor_config.get("threshold", 3)
        timeframe = monitor_config.get("timeframe", 120)

        count = self.action_cache.record_action(guild.id, 0, "kick", timeframe)

        if count >= threshold:
            asyncio.create_task(self._investigate_kicks(guild, monitor_config))

    async def _investigate_kicks(self, guild: discord.Guild, config: dict) -> None:
        """Investigate mass kicks and quarantine culprits."""
        threshold = config.get("threshold", 3)
        timeframe = config.get("timeframe", 120)

        culprits = await self.audit_helper.get_kick_culprit(guild, timeframe, threshold)

        for culprit, count in culprits:
            if await self.is_trusted(guild, culprit):
                continue

            asyncio.create_task(self.quarantine_actions.execute_quarantine(guild, culprit, "kick", self.action_cache))

    async def on_webhooks_update(self, channel: discord.abc.GuildChannel) -> None:
        """Handle webhook update events."""
        guild = channel.guild

        if not await self.is_enabled(guild):
            return

        # Check both create and delete monitors
        create_config = await self.get_monitor_config(guild, "webhook_create")
        delete_config = await self.get_monitor_config(guild, "webhook_delete")

        # We don't know if it was create or delete from this event alone
        # So we check audit logs to determine which
        asyncio.create_task(self._investigate_webhook_change(guild, create_config, delete_config))

    async def _investigate_webhook_change(self, guild: discord.Guild, create_config: dict, delete_config: dict) -> None:
        """Investigate webhook changes."""
        # Check creates
        if create_config.get("enabled", True):
            threshold = create_config.get("threshold", 2)
            timeframe = create_config.get("timeframe", 60)

            culprits = await self.audit_helper.get_webhook_create_culprit(guild, timeframe, threshold)

            for culprit, count in culprits:
                if not await self.is_trusted(guild, culprit):
                    asyncio.create_task(
                        self.quarantine_actions.execute_quarantine(guild, culprit, "webhook_create", self.action_cache)
                    )

        # Check deletes
        if delete_config.get("enabled", True):
            threshold = delete_config.get("threshold", 2)
            timeframe = delete_config.get("timeframe", 60)

            culprits = await self.audit_helper.get_webhook_delete_culprit(guild, timeframe, threshold)

            for culprit, count in culprits:
                if not await self.is_trusted(guild, culprit):
                    asyncio.create_task(
                        self.quarantine_actions.execute_quarantine(guild, culprit, "webhook_delete", self.action_cache)
                    )

    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        """Handle guild update events - detect vanity URL changes."""
        if not await self.is_enabled(after):
            return

        # Check for vanity URL change
        if before.vanity_url_code != after.vanity_url_code:
            monitor_config = await self.get_monitor_config(after, "vanity_change")
            if monitor_config.get("enabled", True):
                asyncio.create_task(self._investigate_vanity_change(after, monitor_config))

    async def _investigate_vanity_change(self, guild: discord.Guild, config: dict) -> None:
        """Investigate vanity URL change and quarantine culprit."""
        timeframe = config.get("timeframe", 60)

        culprit = await self.audit_helper.get_vanity_change_culprit(guild, timeframe)

        if culprit and not await self.is_trusted(guild, culprit):
            asyncio.create_task(
                self.quarantine_actions.execute_quarantine(guild, culprit, "vanity_change", self.action_cache)
            )

    async def on_member_join(self, member: discord.Member) -> None:
        """Handle member join events - detect bot additions."""
        guild = member.guild

        if not await self.is_enabled(guild):
            return

        # Only check if the joining user is a bot
        if not member.bot:
            return

        monitor_config = await self.get_monitor_config(guild, "bot_add")
        if not monitor_config.get("enabled", True):
            return

        # Bot additions are instant action (threshold 1)
        asyncio.create_task(self._investigate_bot_add(guild, member, monitor_config))

    async def _investigate_bot_add(self, guild: discord.Guild, bot_member: discord.Member, config: dict) -> None:
        """Investigate bot addition and quarantine culprit."""
        timeframe = config.get("timeframe", 60)
        kick_bot = config.get("kick_bot", True)

        culprit = await self.audit_helper.get_bot_add_culprit(guild, bot_member.id, timeframe)

        if culprit and not await self.is_trusted(guild, culprit):
            # Quarantine the user who added the bot
            await self.quarantine_actions.execute_quarantine(guild, culprit, "bot_add", self.action_cache)

            # Optionally kick the bot
            if kick_bot:
                await self.quarantine_actions.kick_bot(guild, bot_member)

    async def on_audit_log_entry(self, entry: discord.AuditLogEntry) -> None:
        """Handle audit log entry events - detect guild prunes."""
        guild = entry.guild

        if not guild or not await self.is_enabled(guild):
            return

        # Check for guild prune
        if entry.action == discord.AuditLogAction.member_prune:
            monitor_config = await self.get_monitor_config(guild, "guild_prune")
            if monitor_config.get("enabled", True):
                # Guild prune is instant action (threshold 0)
                if entry.user and not entry.user.bot:
                    culprit = guild.get_member(entry.user.id)
                    if culprit and not await self.is_trusted(guild, culprit):
                        asyncio.create_task(
                            self.quarantine_actions.execute_quarantine(guild, culprit, "guild_prune", self.action_cache)
                        )
