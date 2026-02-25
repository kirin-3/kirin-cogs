"""Audit log utilities for the AntiNuke cog."""

import logging
import time
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import discord
from redbot.core import Config
from redbot.core.bot import Red

from .constants import DANGEROUS_PERMISSIONS

log = logging.getLogger("red.kirin-cogs.antinuke.audit")


class AuditLogHelper:
    """Helper class for fetching and parsing audit logs."""

    def __init__(self, bot: Red, config: Config) -> None:
        self.bot = bot
        self.config = config

    async def get_channel_delete_culprit(
        self, guild: discord.Guild, timeframe: int, threshold: int
    ) -> List[Tuple[discord.Member, int]]:
        """
        Find users who deleted channels within the timeframe.

        Parameters
        ----------
        guild : discord.Guild
            The guild to check.
        timeframe : int
            The timeframe in seconds.
        threshold : int
            The threshold count.

        Returns
        -------
        List[Tuple[discord.Member, int]]
            List of (user, count) tuples for users exceeding threshold.
        """
        return await self._get_culprits(
            guild,
            discord.AuditLogAction.channel_delete,
            timeframe,
            threshold,
        )

    async def get_channel_create_culprit(
        self, guild: discord.Guild, timeframe: int, threshold: int
    ) -> List[Tuple[discord.Member, int]]:
        """
        Find users who created channels within the timeframe.
        """
        return await self._get_culprits(
            guild,
            discord.AuditLogAction.channel_create,
            timeframe,
            threshold,
        )

    async def get_role_delete_culprit(
        self, guild: discord.Guild, timeframe: int, threshold: int
    ) -> List[Tuple[discord.Member, int]]:
        """
        Find users who deleted roles within the timeframe.
        """
        return await self._get_culprits(
            guild,
            discord.AuditLogAction.role_delete,
            timeframe,
            threshold,
        )

    async def get_role_create_culprit(
        self, guild: discord.Guild, timeframe: int, threshold: int
    ) -> List[Tuple[discord.Member, int]]:
        """
        Find users who created roles within the timeframe.
        """
        return await self._get_culprits(
            guild,
            discord.AuditLogAction.role_create,
            timeframe,
            threshold,
        )

    async def get_ban_culprit(
        self, guild: discord.Guild, timeframe: int, threshold: int
    ) -> List[Tuple[discord.Member, int]]:
        """
        Find users who banned members within the timeframe.
        """
        return await self._get_culprits(
            guild,
            discord.AuditLogAction.ban,
            timeframe,
            threshold,
        )

    async def get_kick_culprit(
        self, guild: discord.Guild, timeframe: int, threshold: int
    ) -> List[Tuple[discord.Member, int]]:
        """
        Find users who kicked members within the timeframe.
        """
        return await self._get_culprits(
            guild,
            discord.AuditLogAction.kick,
            timeframe,
            threshold,
        )

    async def get_webhook_create_culprit(
        self, guild: discord.Guild, timeframe: int, threshold: int
    ) -> List[Tuple[discord.Member, int]]:
        """
        Find users who created webhooks within the timeframe.
        """
        return await self._get_culprits(
            guild,
            discord.AuditLogAction.webhook_create,
            timeframe,
            threshold,
        )

    async def get_webhook_delete_culprit(
        self, guild: discord.Guild, timeframe: int, threshold: int
    ) -> List[Tuple[discord.Member, int]]:
        """
        Find users who deleted webhooks within the timeframe.
        """
        return await self._get_culprits(
            guild,
            discord.AuditLogAction.webhook_delete,
            timeframe,
            threshold,
        )

    async def get_prune_culprit(
        self, guild: discord.Guild, timeframe: int
    ) -> Optional[discord.Member]:
        """
        Find user who initiated a guild prune within the timeframe.

        Parameters
        ----------
        guild : discord.Guild
            The guild to check.
        timeframe : int
            The timeframe in seconds.

        Returns
        -------
        Optional[discord.Member]
            The user who initiated the prune, or None.
        """
        try:
            current_time = time.time()
            cutoff = current_time - timeframe

            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.guild_prune,
                limit=5,
            ):
                if entry.created_at.timestamp() > cutoff:
                    if entry.user and not entry.user.bot:
                        return guild.get_member(entry.user.id)
            return None

        except discord.Forbidden:
            log.warning(f"Missing view_audit_log permission in guild {guild.id}")
            return None

    async def get_bot_add_culprit(
        self, guild: discord.Guild, bot_id: int, timeframe: int
    ) -> Optional[discord.Member]:
        """
        Find user who added a bot to the guild.

        Parameters
        ----------
        guild : discord.Guild
            The guild to check.
        bot_id : int
            The bot's user ID.
        timeframe : int
            The timeframe in seconds.

        Returns
        -------
        Optional[discord.Member]
            The user who added the bot, or None.
        """
        try:
            current_time = time.time()
            cutoff = current_time - timeframe

            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.bot_add,
                limit=10,
            ):
                if entry.created_at.timestamp() > cutoff:
                    if entry.target and entry.target.id == bot_id:
                        if entry.user:
                            return guild.get_member(entry.user.id)
            return None

        except discord.Forbidden:
            log.warning(f"Missing view_audit_log permission in guild {guild.id}")
            return None

    async def get_role_update_culprit(
        self,
        guild: discord.Guild,
        role_id: int,
        timeframe: int,
        dangerous_perms: List[str] = None,
    ) -> Optional[Tuple[discord.Member, str]]:
        """
        Find user who updated a role with dangerous permissions.

        Parameters
        ----------
        guild : discord.Guild
            The guild to check.
        role_id : int
            The role ID that was updated.
        timeframe : int
            The timeframe in seconds.
        dangerous_perms : List[str], optional
            List of dangerous permission names.

        Returns
        -------
        Optional[Tuple[discord.Member, str]]
            Tuple of (user, permission_name) or None.
        """
        if dangerous_perms is None:
            dangerous_perms = DANGEROUS_PERMISSIONS

        try:
            current_time = time.time()
            cutoff = current_time - timeframe

            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.role_update,
                limit=20,
            ):
                if entry.created_at.timestamp() <= cutoff:
                    break

                if entry.target and entry.target.id == role_id:
                    # Check if dangerous permissions were added
                    if entry.changes:
                        for change in entry.changes:
                            if change.key == "permissions":
                                # Check which dangerous perms were added
                                if hasattr(change, "new") and hasattr(change, "old"):
                                    try:
                                        old_perms = discord.Permissions(change.old)
                                        new_perms = discord.Permissions(change.new)

                                        for perm_name in dangerous_perms:
                                            if not getattr(
                                                old_perms, perm_name, False
                                            ) and getattr(new_perms, perm_name, False):
                                                if entry.user:
                                                    member = guild.get_member(
                                                        entry.user.id
                                                    )
                                                    if member:
                                                        return (member, perm_name)
                                    except (TypeError, ValueError):
                                        pass
            return None

        except discord.Forbidden:
            log.warning(f"Missing view_audit_log permission in guild {guild.id}")
            return None

    async def get_vanity_change_culprit(
        self, guild: discord.Guild, timeframe: int
    ) -> Optional[discord.Member]:
        """
        Find user who changed the vanity URL.

        Parameters
        ----------
        guild : discord.Guild
            The guild to check.
        timeframe : int
            The timeframe in seconds.

        Returns
        -------
        Optional[discord.Member]
            The user who changed the vanity, or None.
        """
        try:
            current_time = time.time()
            cutoff = current_time - timeframe

            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.guild_update,
                limit=10,
            ):
                if entry.created_at.timestamp() > cutoff:
                    # Check if vanity was changed
                    if entry.changes:
                        for change in entry.changes:
                            if change.key == "vanity_url_code":
                                if entry.user:
                                    return guild.get_member(entry.user.id)
            return None

        except discord.Forbidden:
            log.warning(f"Missing view_audit_log permission in guild {guild.id}")
            return None

    async def _get_culprits(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        timeframe: int,
        threshold: int,
    ) -> List[Tuple[discord.Member, int]]:
        """
        Generic method to find users exceeding action threshold.

        Parameters
        ----------
        guild : discord.Guild
            The guild to check.
        action : discord.AuditLogAction
            The audit log action to look for.
        timeframe : int
            The timeframe in seconds.
        threshold : int
            The threshold count.

        Returns
        -------
        List[Tuple[discord.Member, int]]
            List of (user, count) tuples for users exceeding threshold.
        """
        try:
            user_counts: Dict[int, int] = defaultdict(int)
            current_time = time.time()
            cutoff = current_time - timeframe

            # Fetch recent entries
            entries = [
                entry
                async for entry in guild.audit_logs(action=action, limit=50)
            ]

            for entry in entries:
                # Check if within timeframe
                if entry.created_at.timestamp() <= cutoff:
                    continue

                if entry.user:
                    user_counts[entry.user.id] += 1

            # Find users exceeding threshold
            culprits = []
            for user_id, count in user_counts.items():
                if count >= threshold:
                    member = guild.get_member(user_id)
                    if member:
                        culprits.append((member, count))

            return culprits

        except discord.Forbidden:
            log.warning(f"Missing view_audit_log permission in guild {guild.id}")
            return []
