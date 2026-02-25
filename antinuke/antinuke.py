"""Main AntiNuke cog class."""

import logging
from typing import Optional

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import inline

from .actions import QuarantineActions
from .audit import AuditLogHelper
from .constants import CONFIG_IDENTIFIER, DEFAULT_GLOBAL, DEFAULT_GUILD
from .events import EventHandlers
from .utils import ActionCache

log = logging.getLogger("red.kirin-cogs.antinuke")


class CompositeMetaClass(type(commands.Cog), type):
    """Allows the cog to inherit from multiple command classes."""

    pass


class AntiNuke(
    commands.Cog,
    metaclass=CompositeMetaClass,
):
    """
    AntiNuke - Server protection against rogue administrators.

    This cog monitors server events and automatically quarantines users
    who perform potentially destructive actions beyond configured thresholds.

    Features:
    - Channel/Role creation and deletion monitoring
    - Ban/Kick monitoring
    - Webhook creation/deletion monitoring
    - Dangerous permission addition detection
    - Vanity URL change detection
    - Guild prune detection
    - Bot addition detection with auto-kick option
    """

    __version__ = "1.0.0"
    __author__ = "kirin"

    def __init__(self, bot: Red) -> None:
        self.bot = bot

        # Initialize Config
        self.config = Config.get_conf(
            self, identifier=CONFIG_IDENTIFIER, force_registration=True
        )
        self.config.register_global(**DEFAULT_GLOBAL)
        self.config.register_guild(**DEFAULT_GUILD)

        # Initialize components
        self.action_cache = ActionCache()
        self.audit_helper = AuditLogHelper(bot, self.config)
        self.quarantine_actions = QuarantineActions(bot, self.config)
        self.event_handlers = EventHandlers(
            bot, self.config, self.action_cache, self.audit_helper, self.quarantine_actions
        )

        # Event listener references
        self._listeners_registered = False

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        log.info("AntiNuke cog loaded")

    async def cog_unload(self) -> None:
        """Called when the cog is unloaded."""
        log.info("AntiNuke cog unloaded")

    # Expose config for command classes
    @property
    def config_ref(self) -> Config:
        """Reference to config for command classes."""
        return self.config

    # Expose action_cache for command classes
    @property
    def action_cache_ref(self) -> ActionCache:
        """Reference to action cache for command classes."""
        return self.action_cache

    # Expose quarantine_actions for command classes
    @property
    def quarantine_actions_ref(self) -> QuarantineActions:
        """Reference to quarantine actions for command classes."""
        return self.quarantine_actions

    # ==================== Event Listeners ====================

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        """Handle channel deletion events."""
        await self.event_handlers.on_guild_channel_delete(channel)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        """Handle channel creation events."""
        await self.event_handlers.on_guild_channel_create(channel)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        """Handle role deletion events."""
        await self.event_handlers.on_guild_role_delete(role)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        """Handle role creation events."""
        await self.event_handlers.on_guild_role_create(role)

    @commands.Cog.listener()
    async def on_guild_role_update(
        self, before: discord.Role, after: discord.Role
    ) -> None:
        """Handle role update events."""
        await self.event_handlers.on_guild_role_update(before, after)

    @commands.Cog.listener()
    async def on_member_ban(
        self, guild: discord.Guild, user: discord.User
    ) -> None:
        """Handle member ban events."""
        await self.event_handlers.on_member_ban(guild, user)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Handle member remove events."""
        await self.event_handlers.on_member_remove(member)

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel) -> None:
        """Handle webhook update events."""
        await self.event_handlers.on_webhooks_update(channel)

    @commands.Cog.listener()
    async def on_guild_update(
        self, before: discord.Guild, after: discord.Guild
    ) -> None:
        """Handle guild update events."""
        await self.event_handlers.on_guild_update(before, after)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Handle member join events."""
        await self.event_handlers.on_member_join(member)

    @commands.Cog.listener()
    async def on_audit_log_entry(self, entry: discord.AuditLogEntry) -> None:
        """Handle audit log entry events."""
        await self.event_handlers.on_audit_log_entry(entry)

    # ==================== Helper Methods ====================

    async def is_enabled(self, guild: discord.Guild) -> bool:
        """Check if AntiNuke is enabled for a guild."""
        return await self.config.guild(guild).enabled()

    async def is_trusted(self, guild: discord.Guild, user: discord.Member) -> bool:
        """Check if a user is trusted."""
        return await self.event_handlers.is_trusted(guild, user)

    async def get_quarantine_role(
        self, guild: discord.Guild
    ) -> Optional[discord.Role]:
        """Get the configured quarantine role for a guild."""
        role_id = await self.config.guild(guild).quarantine_role()
        if role_id:
            return guild.get_role(role_id)
        return None

    # ==================== Commands from config.py ====================

    @commands.group(name="antinuke", aliases=["an"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def antinuke(self, ctx: commands.Context) -> None:
        """AntiNuke configuration commands."""
        pass

    @antinuke.command(name="enable")
    async def antinuke_enable(self, ctx: commands.Context) -> None:
        """Enable AntiNuke for this server."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send(f"✅ AntiNuke has been **enabled** for this server.")

    @antinuke.command(name="disable")
    async def antinuke_disable(self, ctx: commands.Context) -> None:
        """Disable AntiNuke for this server."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send(f"❌ AntiNuke has been **disabled** for this server.")

    @antinuke.command(name="logchannel")
    async def antinuke_logchannel(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """Set the log channel for AntiNuke alerts."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"✅ AntiNuke log channel set to {channel.mention}.")

    @antinuke.command(name="quarantinerole")
    async def antinuke_quarantinerole(
        self, ctx: commands.Context, role: discord.Role
    ) -> None:
        """Set the quarantine role.

        This role should have minimal permissions and be positioned
        below the bot's highest role.
        """
        if ctx.guild.me.top_role <= role:
            await ctx.send(
                "❌ The quarantine role must be **below** the bot's highest role."
            )
            return

        await self.config.guild(ctx.guild).quarantine_role.set(role.id)
        await ctx.send(f"✅ Quarantine role set to {role.mention}.")

    @antinuke.command(name="settings", aliases=["show"])
    async def antinuke_settings(self, ctx: commands.Context) -> None:
        """Show current AntiNuke settings."""
        from .constants import ACTION_NAMES, DEFAULT_MONITOR_CONFIG
        from redbot.core.utils.chat_formatting import pagify

        guild_config = await self.config.guild(ctx.guild).all()

        enabled = guild_config.get("enabled", False)
        log_channel_id = guild_config.get("log_channel")
        quarantine_role_id = guild_config.get("quarantine_role")
        trusted_users = guild_config.get("trusted_users", [])
        trusted_roles = guild_config.get("trusted_roles", [])
        monitor = guild_config.get("monitor", {})

        status = "🟢 Enabled" if enabled else "🔴 Disabled"

        lines = [
            f"## AntiNuke Settings for {ctx.guild.name}",
            "",
            f"**Status:** {status}",
            "",
            "### Core Settings",
        ]

        if log_channel_id:
            log_channel = ctx.guild.get_channel(log_channel_id)
            if log_channel:
                lines.append(f"**Log Channel:** {log_channel.mention}")
            else:
                lines.append(f"**Log Channel:** {inline(f'Unknown ({log_channel_id})')}")
        else:
            lines.append("**Log Channel:** Not set")

        if quarantine_role_id:
            quarantine_role = ctx.guild.get_role(quarantine_role_id)
            if quarantine_role:
                lines.append(f"**Quarantine Role:** {quarantine_role.mention}")
            else:
                lines.append(
                    f"**Quarantine Role:** {inline(f'Unknown ({quarantine_role_id})')}"
                )
        else:
            lines.append("**Quarantine Role:** Not set")

        if trusted_users:
            user_mentions = []
            for user_id in trusted_users[:10]:
                user = ctx.guild.get_member(user_id)
                if user:
                    user_mentions.append(user.mention)
            if user_mentions:
                lines.append(f"**Trusted Users:** {', '.join(user_mentions)}")
            else:
                lines.append(f"**Trusted Users:** {len(trusted_users)} user(s)")
        else:
            lines.append("**Trusted Users:** None")

        if trusted_roles:
            role_mentions = []
            for role_id in trusted_roles[:10]:
                role = ctx.guild.get_role(role_id)
                if role:
                    role_mentions.append(role.mention)
            lines.append(f"**Trusted Roles:** {', '.join(role_mentions)}")
        else:
            lines.append("**Trusted Roles:** None")

        lines.append("")
        lines.append("### Monitor Settings")

        for action_type, action_name in ACTION_NAMES.items():
            action_config = monitor.get(action_type, DEFAULT_MONITOR_CONFIG)
            if action_config.get("enabled", True):
                threshold = action_config.get("threshold", 2)
                timeframe = action_config.get("timeframe", 60)
                lines.append(f"- **{action_name}:** Threshold {threshold} / {timeframe}s")
            else:
                lines.append(f"- **{action_name}:** Disabled")

        text = "\n".join(lines)
        for page in pagify(text, page_length=2000):
            await ctx.send(page)

    # Monitor group
    @antinuke.group(name="monitor", aliases=["mon"])
    async def antinuke_monitor(self, ctx: commands.Context) -> None:
        """Configure monitoring settings for specific actions."""
        pass

    @antinuke_monitor.command(name="enable")
    async def monitor_enable(
        self, ctx: commands.Context, action_type: str.lower
    ) -> None:
        """Enable monitoring for a specific action type."""
        from .constants import ACTION_NAMES, DEFAULT_MONITOR_CONFIG

        if action_type not in ACTION_NAMES:
            await ctx.send(
                f"❌ Invalid action type. Valid types: {', '.join(ACTION_NAMES.keys())}"
            )
            return

        async with self.config.guild(ctx.guild).monitor() as monitor:
            if action_type not in monitor:
                monitor[action_type] = DEFAULT_MONITOR_CONFIG.copy()
            monitor[action_type]["enabled"] = True

        await ctx.send(
            f"✅ Monitoring enabled for **{ACTION_NAMES[action_type]}**."
        )

    @antinuke_monitor.command(name="disable")
    async def monitor_disable(
        self, ctx: commands.Context, action_type: str.lower
    ) -> None:
        """Disable monitoring for a specific action type."""
        from .constants import ACTION_NAMES, DEFAULT_MONITOR_CONFIG

        if action_type not in ACTION_NAMES:
            await ctx.send(
                f"❌ Invalid action type. Valid types: {', '.join(ACTION_NAMES.keys())}"
            )
            return

        async with self.config.guild(ctx.guild).monitor() as monitor:
            if action_type not in monitor:
                monitor[action_type] = DEFAULT_MONITOR_CONFIG.copy()
            monitor[action_type]["enabled"] = False

        await ctx.send(
            f"❌ Monitoring disabled for **{ACTION_NAMES[action_type]}**."
        )

    @antinuke_monitor.command(name="threshold")
    async def monitor_threshold(
        self,
        ctx: commands.Context,
        action_type: str.lower,
        threshold: int,
        timeframe: int = 60,
    ) -> None:
        """Set the threshold for an action type."""
        from .constants import ACTION_NAMES, DEFAULT_MONITOR_CONFIG

        if action_type not in ACTION_NAMES:
            await ctx.send(
                f"❌ Invalid action type. Valid types: {', '.join(ACTION_NAMES.keys())}"
            )
            return

        if threshold < 0:
            await ctx.send("❌ Threshold must be 0 or greater.")
            return

        if timeframe < 10:
            await ctx.send("❌ Timeframe must be at least 10 seconds.")
            return

        async with self.config.guild(ctx.guild).monitor() as monitor:
            if action_type not in monitor:
                monitor[action_type] = DEFAULT_MONITOR_CONFIG.copy()
            monitor[action_type]["threshold"] = threshold
            monitor[action_type]["timeframe"] = timeframe

        if threshold == 0:
            await ctx.send(
                f"✅ **{ACTION_NAMES[action_type]}** set to instant action."
            )
        else:
            await ctx.send(
                f"✅ **{ACTION_NAMES[action_type]}** threshold set to {threshold} "
                f"actions within {timeframe} seconds."
            )

    @antinuke_monitor.command(name="botkick")
    async def monitor_botkick(
        self, ctx: commands.Context, enabled: bool
    ) -> None:
        """Configure whether to automatically kick unauthorized bots."""
        from .constants import DEFAULT_MONITOR_CONFIG

        async with self.config.guild(ctx.guild).monitor() as monitor:
            if "bot_add" not in monitor:
                monitor["bot_add"] = DEFAULT_MONITOR_CONFIG.copy()
            monitor["bot_add"]["kick_bot"] = enabled

        if enabled:
            await ctx.send("✅ Auto-kick for unauthorized bots is now **enabled**.")
        else:
            await ctx.send("❌ Auto-kick for unauthorized bots is now **disabled**.")

    # Trust group
    @antinuke.group(name="trust", aliases=["trusted"])
    async def antinuke_trust(self, ctx: commands.Context) -> None:
        """Manage trusted users and roles."""
        pass

    @antinuke_trust.command(name="adduser")
    async def trust_adduser(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Add a user to the trusted list."""
        if user.bot:
            await ctx.send("❌ Bots cannot be added to the trusted list.")
            return

        if user.id == ctx.guild.owner_id:
            await ctx.send("ℹ️ The server owner is always trusted by default.")
            return

        async with self.config.guild(ctx.guild).trusted_users() as trusted:
            if user.id in trusted:
                await ctx.send(f"❌ {user.mention} is already trusted.")
                return
            trusted.append(user.id)

        await ctx.send(f"✅ {user.mention} has been added to the trusted list.")

    @antinuke_trust.command(name="removeuser", aliases=["deluser", "rmuser"])
    async def trust_removeuser(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Remove a user from the trusted list."""
        async with self.config.guild(ctx.guild).trusted_users() as trusted:
            if user.id not in trusted:
                await ctx.send(f"❌ {user.mention} is not in the trusted list.")
                return
            trusted.remove(user.id)

        await ctx.send(f"✅ {user.mention} has been removed from the trusted list.")

    @antinuke_trust.command(name="addrole")
    async def trust_addrole(
        self, ctx: commands.Context, role: discord.Role
    ) -> None:
        """Add a role to the trusted list."""
        if role.is_default():
            await ctx.send("❌ The @everyone role cannot be trusted.")
            return

        async with self.config.guild(ctx.guild).trusted_roles() as trusted:
            if role.id in trusted:
                await ctx.send(f"❌ {role.mention} is already trusted.")
                return
            trusted.append(role.id)

        await ctx.send(f"✅ {role.mention} has been added to the trusted roles.")

    @antinuke_trust.command(name="removerole", aliases=["delrole", "rmrole"])
    async def trust_removerole(
        self, ctx: commands.Context, role: discord.Role
    ) -> None:
        """Remove a role from the trusted list."""
        async with self.config.guild(ctx.guild).trusted_roles() as trusted:
            if role.id not in trusted:
                await ctx.send(f"❌ {role.mention} is not in the trusted list.")
                return
            trusted.remove(role.id)

        await ctx.send(f"✅ {role.mention} has been removed from the trusted roles.")

    @antinuke_trust.command(name="list", aliases=["show"])
    async def trust_list(self, ctx: commands.Context) -> None:
        """Show all trusted users and roles."""
        trusted_users = await self.config.guild(ctx.guild).trusted_users()
        trusted_roles = await self.config.guild(ctx.guild).trusted_roles()

        lines = [
            "## 🔒 AntiNuke Trust List",
            "",
            "**Note:** The server owner is always trusted.",
            "",
        ]

        if trusted_users:
            user_lines = []
            for user_id in trusted_users:
                user = ctx.guild.get_member(user_id)
                if user:
                    user_lines.append(f"- {user.mention} ({inline(str(user_id))})")
                else:
                    user_lines.append(f"- Unknown user ({inline(str(user_id))})")
            lines.append(f"### Trusted Users ({len(trusted_users)})")
            lines.extend(user_lines)
        else:
            lines.append("### Trusted Users")
            lines.append("None")

        lines.append("")

        if trusted_roles:
            role_lines = []
            for role_id in trusted_roles:
                role = ctx.guild.get_role(role_id)
                if role:
                    role_lines.append(f"- {role.mention} ({inline(str(role_id))})")
                else:
                    role_lines.append(f"- Unknown role ({inline(str(role_id))})")
            lines.append(f"### Trusted Roles ({len(trusted_roles)})")
            lines.extend(role_lines)
        else:
            lines.append("### Trusted Roles")
            lines.append("None")

        await ctx.send("\n".join(lines))

    @antinuke_trust.command(name="clear")
    async def trust_clear(self, ctx: commands.Context) -> None:
        """Clear all trusted users and roles."""
        await self.config.guild(ctx.guild).trusted_users.set([])
        await self.config.guild(ctx.guild).trusted_roles.set([])
        await ctx.send("✅ All trusted users and roles have been cleared.")

    # Quarantine group
    @antinuke.group(name="quarantine", aliases=["q"])
    async def antinuke_quarantine(self, ctx: commands.Context) -> None:
        """Manage quarantined users."""
        pass

    @antinuke_quarantine.command(name="list", aliases=["show"])
    async def quarantine_list(self, ctx: commands.Context) -> None:
        """Show all currently quarantined users."""
        from .constants import ACTION_NAMES
        from redbot.core.utils.chat_formatting import pagify

        quarantined = await self.config.guild(ctx.guild).quarantined_users()

        if not quarantined:
            await ctx.send("No users are currently quarantined.")
            return

        lines = [
            f"## 🛡️ Quarantined Users in {ctx.guild.name}",
            "",
        ]

        for user_id, data in quarantined.items():
            user = ctx.guild.get_member(int(user_id))
            trigger = ACTION_NAMES.get(
                data.get("trigger_action", "unknown"), "Unknown"
            )
            timestamp = data.get("quarantined_at", "Unknown time")

            if user:
                lines.append(f"### {user.mention} ({inline(str(user_id))})")
            else:
                lines.append(f"### Unknown User ({inline(str(user_id))})")

            lines.append(f"- **Trigger:** {trigger}")
            lines.append(f"- **Quarantined:** {timestamp}")

            roles = data.get("roles", [])
            if roles:
                lines.append(f"- **Stored Roles:** {len(roles)} role(s)")

            lines.append("")

        text = "\n".join(lines)
        for page in pagify(text, page_length=2000):
            await ctx.send(page)

    @antinuke_quarantine.command(name="restore", aliases=["unquarantine", "unq"])
    async def quarantine_restore(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Restore a quarantined user's roles."""
        quarantined = await self.config.guild(ctx.guild).quarantined_users()

        if str(user.id) not in quarantined:
            await ctx.send(f"❌ {user.mention} is not quarantined.")
            return

        success = await self.quarantine_actions.restore_user(
            ctx.guild, user, restored_by=ctx.author.name
        )

        if success:
            await ctx.send(f"✅ {user.mention} has been restored.")
        else:
            await ctx.send(
                f"❌ Failed to restore {user.mention}. Check bot permissions and role hierarchy."
            )

    @antinuke_quarantine.command(name="force")
    async def quarantine_force(
        self, ctx: commands.Context, user: discord.Member, *, reason: str = "Manual quarantine"
    ) -> None:
        """Forcibly quarantine a user."""
        if ctx.guild.me.top_role <= user.top_role:
            await ctx.send(
                f"❌ Cannot quarantine {user.mention} - they have equal or higher roles."
            )
            return

        if user.id == ctx.guild.owner_id:
            await ctx.send("❌ Cannot quarantine the server owner.")
            return

        success = await self.quarantine_actions.execute_quarantine(
            ctx.guild, user, f"manual: {reason}", self.action_cache
        )

        if success:
            await ctx.send(f"✅ {user.mention} has been quarantined.")
        else:
            await ctx.send(
                f"❌ Failed to quarantine {user.mention}. Check bot permissions and role hierarchy."
            )

    @antinuke_quarantine.command(name="clear")
    async def quarantine_clear(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Clear a user from quarantine records without restoring roles."""
        async with self.config.guild(ctx.guild).quarantined_users() as q_users:
            if str(user.id) not in q_users:
                await ctx.send(f"❌ {user.mention} is not in quarantine records.")
                return
            del q_users[str(user.id)]

        await ctx.send(
            f"✅ {user.mention} has been cleared from quarantine records."
        )

    @antinuke_quarantine.command(name="info")
    async def quarantine_info(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Show detailed quarantine information for a user."""
        from .constants import ACTION_NAMES
        import datetime

        quarantined = await self.config.guild(ctx.guild).quarantined_users()

        if str(user.id) not in quarantined:
            await ctx.send(f"❌ {user.mention} is not quarantined.")
            return

        data = quarantined[str(user.id)]

        trigger = ACTION_NAMES.get(
            data.get("trigger_action", "unknown"), "Unknown"
        )
        reason = data.get("reason", "Unknown reason")
        timestamp = data.get("quarantined_at", "Unknown time")
        stored_roles = data.get("roles", [])

        embed = discord.Embed(
            title=f"🛡️ Quarantine Info: {user}",
            color=discord.Color.orange(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )

        embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="User", value=f"{user.mention}\n{inline(str(user.id))}", inline=True)
        embed.add_field(name="Trigger", value=f"**{trigger}**", inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)

        embed.add_field(name="Quarantined At", value=timestamp, inline=False)

        if stored_roles:
            role_list = []
            missing_roles = []
            for role_id in stored_roles:
                role = ctx.guild.get_role(role_id)
                if role:
                    role_list.append(role.mention)
                else:
                    missing_roles.append(str(role_id))

            if role_list:
                roles_text = ", ".join(role_list[:10])
                if len(role_list) > 10:
                    roles_text += f" ... and {len(role_list) - 10} more"
                embed.add_field(
                    name=f"Stored Roles ({len(stored_roles)})",
                    value=roles_text,
                    inline=False,
                )

            if missing_roles:
                embed.add_field(
                    name="Missing Roles",
                    value=f"{len(missing_roles)} role(s) no longer exist",
                    inline=False,
                )
        else:
            embed.add_field(name="Stored Roles", value="None", inline=False)

        await ctx.send(embed=embed)

    @antinuke_quarantine.command(name="cleanup")
    async def quarantine_cleanup(self, ctx: commands.Context) -> None:
        """Clean up quarantine records for users who have left the server."""
        quarantined = await self.config.guild(ctx.guild).quarantined_users()

        if not quarantined:
            await ctx.send("No quarantined users to clean up.")
            return

        removed = 0
        async with self.config.guild(ctx.guild).quarantined_users() as q_users:
            for user_id in list(q_users.keys()):
                member = ctx.guild.get_member(int(user_id))
                if not member:
                    del q_users[user_id]
                    removed += 1

        if removed:
            await ctx.send(f"✅ Cleaned up {removed} quarantine record(s) for users who left.")
        else:
            await ctx.send("No cleanup needed - all quarantined users are still in the server.")
