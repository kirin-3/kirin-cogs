"""Quarantine, restore, and notification actions for the AntiNuke cog."""

import asyncio
import datetime
import logging
from typing import List

import discord
from redbot.core import Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import bold, inline

from .constants import ACTION_NAMES
from .utils import is_above_in_hierarchy

log = logging.getLogger("red.kirin-cogs.antinuke.actions")


class QuarantineActions:
    """Handles quarantine, restore, and notification actions."""

    def __init__(self, bot: Red, config: Config) -> None:
        self.bot = bot
        self.config = config

    async def execute_quarantine(
        self,
        guild: discord.Guild,
        user: discord.Member,
        trigger_action: str,
        action_cache=None,
    ) -> bool:
        """
        Atomically quarantine a user with a single API call.

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
            True if successful, False if hierarchy prevents action.
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
            log.warning(
                f"Quarantine attempted in guild {guild.id} but no quarantine role is set"
            )
            return False

        quarantine_role = guild.get_role(quarantine_role_id)
        if not quarantine_role:
            log.warning(
                f"Quarantine role {quarantine_role_id} not found in guild {guild.id}"
            )
            return False

        # Check hierarchy for quarantine role
        if bot_member.top_role <= quarantine_role:
            log.warning(
                f"Quarantine role is above bot's top role in guild {guild.id}"
            )
            return False

        # Store current roles BEFORE stripping (for restoration later)
        role_ids = [role.id for role in user.roles if role != guild.default_role]

        quarantine_data = {
            "roles": role_ids,
            "reason": f"AntiNuke triggered: {trigger_action}",
            "quarantined_by": "anti-nuke",
            "quarantined_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "trigger_action": trigger_action,
        }

        # Store in Config (this is persistent data we need to keep)
        async with self.config.guild(guild).quarantined_users() as q_users:
            q_users[str(user.id)] = quarantine_data

        try:
            # SINGLE API CALL - Atomic role replacement
            await user.edit(
                roles=[quarantine_role],
                reason=f"AntiNuke: {ACTION_NAMES.get(trigger_action, trigger_action)} threshold exceeded",
            )

            # Clear action cache for this user
            if action_cache:
                action_cache.clear_user(guild.id, user.id)

            # Log the action (non-blocking)
            asyncio.create_task(self.log_quarantine(guild, user, trigger_action))

            return True

        except discord.Forbidden:
            # Still notify owner even after hierarchy check (race condition)
            await self.notify_owner_hierarchy_issue(guild, user, trigger_action)
            return False
        except discord.HTTPException as e:
            log.error(f"Failed to quarantine user {user.id} in guild {guild.id}: {e}")
            return False

    async def restore_user(
        self, guild: discord.Guild, user: discord.Member, restored_by: str = "manual"
    ) -> bool:
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
        roles_to_restore: List[discord.Role] = []
        missing_roles: List[int] = []

        for role_id in user_data.get("roles", []):
            role = guild.get_role(role_id)
            if role:
                # Check if bot can assign this role
                if guild.me.top_role > role:
                    roles_to_restore.append(role)
                else:
                    log.warning(
                        f"Cannot restore role {role_id} to user {user.id}: role is above bot's top role"
                    )
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
                if role != guild.default_role and role != quarantine_role:
                    if role not in final_roles:
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
            asyncio.create_task(
                self.log_restoration(guild, user, restored_by, missing_roles)
            )

            return True

        except discord.Forbidden:
            log.error(
                f"Failed to restore user {user.id} in guild {guild.id}: missing permissions"
            )
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
            log.warning(
                f"Failed to kick bot {bot_user.id} in guild {guild.id}: missing permissions"
            )
            return False
        except discord.HTTPException as e:
            log.error(f"Failed to kick bot {bot_user.id} in guild {guild.id}: {e}")
            return False

    async def log_quarantine(
        self,
        guild: discord.Guild,
        user: discord.Member,
        trigger_action: str,
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
        """
        log_channel_id = await self.config.guild(guild).log_channel()
        if not log_channel_id:
            return

        log_channel = guild.get_channel(log_channel_id)
        if not log_channel:
            return

        action_name = ACTION_NAMES.get(trigger_action, trigger_action)

        embed = discord.Embed(
            title="🛡️ AntiNuke Quarantine",
            description=f"{user.mention} has been quarantined.",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        embed.add_field(name="User", value=f"{user} (`{user.id}`)", inline=True)
        embed.add_field(name="Trigger", value=bold(action_name), inline=True)
        embed.add_field(
            name="Roles Stripped",
            value=str(len(user.roles) - 1),  # -1 for @everyone
            inline=True,
        )

        embed.set_footer(text=f"Guild: {guild.name}")

        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            log.warning(
                f"Cannot send to log channel {log_channel_id} in guild {guild.id}"
            )

    async def log_restoration(
        self,
        guild: discord.Guild,
        user: discord.Member,
        restored_by: str,
        missing_roles: List[int],
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
        if not log_channel:
            return

        embed = discord.Embed(
            title="✅ AntiNuke Restoration",
            description=f"{user.mention} has been unquarantined.",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
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
            log.warning(
                f"Cannot send to log channel {log_channel_id} in guild {guild.id}"
            )

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
            if log_channel:
                embed = discord.Embed(
                    title="⚠️ AntiNuke Hierarchy Issue",
                    description=f"Cannot quarantine {user.mention} - they have equal or higher roles than the bot.",
                    color=discord.Color.orange(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )

                embed.add_field(
                    name="User", value=f"{user} (`{user.id}`)", inline=True
                )
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

                embed.add_field(
                    name="User", value=f"{user} (`{user.id}`)", inline=True
                )
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
                log.warning(
                    f"Cannot DM owner {owner.id} about hierarchy issue in guild {guild.id}"
                )

    async def notify_owner_missing_permissions(
        self, guild: discord.Guild, permission: str
    ) -> None:
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
            if log_channel:
                try:
                    await log_channel.send(
                        f"⚠️ AntiNuke is missing the `{permission}` permission. "
                        "Some features may not work correctly."
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
                log.warning(
                    f"Cannot DM owner {owner.id} about missing permissions in guild {guild.id}"
                )
