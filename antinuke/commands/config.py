"""Configuration commands for the AntiNuke cog."""

from typing import TYPE_CHECKING

import discord
from redbot.core import app_commands, commands
from redbot.core.utils.chat_formatting import bold, inline, pagify

from ..constants import ACTION_NAMES, DEFAULT_MONITOR_CONFIG

if TYPE_CHECKING:
    from redbot.core import Config

    from antinuke.actions import QuarantineActions
    from antinuke.utils import ActionCache


class AntiNukeConfigCommands(commands.Cog):
    """Configuration commands for AntiNuke."""

    config: "Config"
    action_cache: "ActionCache"
    quarantine_actions: "QuarantineActions"

    @commands.group(name="antinuke", aliases=["an"])  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def antinuke(self, ctx: commands.Context) -> None:
        """AntiNuke configuration commands."""
        pass

    @antinuke.command(name="enable")
    async def antinuke_enable(self, ctx: commands.Context) -> None:
        """Enable AntiNuke for this server."""
        guild = ctx.guild
        if not guild:
            return
        await self.config.guild(guild).enabled.set(True)
        await ctx.send(f"✅ AntiNuke has been {bold('enabled')} for this server.")

    @antinuke.command(name="disable")
    async def antinuke_disable(self, ctx: commands.Context) -> None:
        """Disable AntiNuke for this server."""
        guild = ctx.guild
        if not guild:
            return
        await self.config.guild(guild).enabled.set(False)
        await ctx.send(f"❌ AntiNuke has been {bold('disabled')} for this server.")

    @antinuke.command(name="logchannel")
    @app_commands.describe(channel="The channel to send AntiNuke logs to")
    async def antinuke_logchannel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set the log channel for AntiNuke alerts."""
        guild = ctx.guild
        if not guild:
            return
        await self.config.guild(guild).log_channel.set(channel.id)
        await ctx.send(f"✅ AntiNuke log channel set to {channel.mention}.")

    @antinuke.command(name="quarantinerole")
    @app_commands.describe(role="The role to assign to quarantined users")
    async def antinuke_quarantinerole(self, ctx: commands.Context, role: discord.Role) -> None:
        """Set the quarantine role.

        This role should have minimal permissions and be positioned
        below the bot's highest role.
        """
        guild = ctx.guild
        if not guild:
            return
        # Check hierarchy
        if guild.me.top_role <= role:
            await ctx.send("❌ The quarantine role must be **below** the bot's highest role.")
            return

        await self.config.guild(guild).quarantine_role.set(role.id)
        await ctx.send(f"✅ Quarantine role set to {role.mention}.")

    @antinuke.command(name="settings", aliases=["show"])
    async def antinuke_settings(self, ctx: commands.Context) -> None:
        """Show current AntiNuke settings."""
        guild = ctx.guild
        if not guild:
            return
        guild_config = await self.config.guild(guild).all()

        enabled = guild_config.get("enabled", False)
        log_channel_id = guild_config.get("log_channel")
        quarantine_role_id = guild_config.get("quarantine_role")
        trusted_users = guild_config.get("trusted_users", [])
        trusted_roles = guild_config.get("trusted_roles", [])
        monitor = guild_config.get("monitor", {})

        # Build status text
        status = "🟢 Enabled" if enabled else "🔴 Disabled"

        lines = [
            f"## AntiNuke Settings for {guild.name}",
            "",
            f"**Status:** {status}",
            "",
            "### Core Settings",
        ]

        # Log channel
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                lines.append(f"**Log Channel:** {log_channel.mention}")
            else:
                lines.append(f"**Log Channel:** {inline(f'Unknown ({log_channel_id})')}")
        else:
            lines.append("**Log Channel:** Not set")

        # Quarantine role
        if quarantine_role_id:
            quarantine_role = guild.get_role(quarantine_role_id)
            if quarantine_role:
                lines.append(f"**Quarantine Role:** {quarantine_role.mention}")
            else:
                lines.append(f"**Quarantine Role:** {inline(f'Unknown ({quarantine_role_id})')}")
        else:
            lines.append("**Quarantine Role:** Not set")

        # Trusted users
        if trusted_users:
            user_mentions = []
            for user_id in trusted_users[:10]:  # Limit to 10
                user = guild.get_member(user_id)
                if user:
                    user_mentions.append(user.mention)
            if user_mentions:
                lines.append(f"**Trusted Users:** {', '.join(user_mentions)}")
            else:
                lines.append(f"**Trusted Users:** {len(trusted_users)} user(s)")
        else:
            lines.append("**Trusted Users:** None")

        # Trusted roles
        if trusted_roles:
            role_mentions = []
            for role_id in trusted_roles[:10]:
                role = guild.get_role(role_id)
                if role:
                    role_mentions.append(role.mention)
            lines.append(f"**Trusted Roles:** {', '.join(role_mentions)}")
        else:
            lines.append("**Trusted Roles:** None")

        # Monitor settings
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

        # Send paginated response
        text = "\n".join(lines)
        for page in pagify(text, page_length=2000):
            await ctx.send(page)

    @antinuke.group(name="monitor", aliases=["mon"])
    async def antinuke_monitor(self, ctx: commands.Context) -> None:
        """Configure monitoring settings for specific actions."""
        pass

    @antinuke_monitor.command(name="enable")
    @app_commands.describe(action_type="The action type to enable monitoring for")
    async def monitor_enable(self, ctx: commands.Context, action_type: str) -> None:
        """Enable monitoring for a specific action type.

        Available action types:
        - channel_create, channel_delete
        - role_create, role_delete
        - ban, kick
        - guild_prune
        - webhook_create, webhook_delete
        - dangerous_permission_add
        - vanity_change
        - bot_add
        """
        guild = ctx.guild
        if not guild:
            return
        action_type = action_type.lower()
        if action_type not in ACTION_NAMES:
            await ctx.send(f"❌ Invalid action type. Valid types: {', '.join(ACTION_NAMES.keys())}")
            return

        async with self.config.guild(guild).monitor() as monitor:
            if action_type not in monitor:
                monitor[action_type] = DEFAULT_MONITOR_CONFIG.copy()
            monitor[action_type]["enabled"] = True

        await ctx.send(f"✅ Monitoring enabled for **{ACTION_NAMES[action_type]}**.")

    @antinuke_monitor.command(name="disable")
    @app_commands.describe(action_type="The action type to disable monitoring for")
    async def monitor_disable(self, ctx: commands.Context, action_type: str) -> None:
        """Disable monitoring for a specific action type."""
        guild = ctx.guild
        if not guild:
            return
        action_type = action_type.lower()
        if action_type not in ACTION_NAMES:
            await ctx.send(f"❌ Invalid action type. Valid types: {', '.join(ACTION_NAMES.keys())}")
            return

        async with self.config.guild(guild).monitor() as monitor:
            if action_type not in monitor:
                monitor[action_type] = DEFAULT_MONITOR_CONFIG.copy()
            monitor[action_type]["enabled"] = False

        await ctx.send(f"❌ Monitoring disabled for **{ACTION_NAMES[action_type]}**.")

    @antinuke_monitor.command(name="threshold")
    @app_commands.describe(
        action_type="The action type to configure",
        threshold="Number of actions allowed within timeframe (0 = instant)",
        timeframe="Time window in seconds",
    )
    async def monitor_threshold(
        self,
        ctx: commands.Context,
        action_type: str,
        threshold: int,
        timeframe: int = 60,
    ) -> None:
        """Set the threshold for an action type.

        Threshold is the number of actions allowed within the timeframe.
        Set to 0 for instant action (like guild_prune).
        """
        guild = ctx.guild
        if not guild:
            return
        action_type = action_type.lower()
        if action_type not in ACTION_NAMES:
            await ctx.send(f"❌ Invalid action type. Valid types: {', '.join(ACTION_NAMES.keys())}")
            return

        if threshold < 0:
            await ctx.send("❌ Threshold must be 0 or greater.")
            return

        if timeframe < 10:
            await ctx.send("❌ Timeframe must be at least 10 seconds.")
            return

        async with self.config.guild(guild).monitor() as monitor:
            if action_type not in monitor:
                monitor[action_type] = DEFAULT_MONITOR_CONFIG.copy()
            monitor[action_type]["threshold"] = threshold
            monitor[action_type]["timeframe"] = timeframe

        if threshold == 0:
            await ctx.send(f"✅ **{ACTION_NAMES[action_type]}** set to instant action.")
        else:
            await ctx.send(
                f"✅ **{ACTION_NAMES[action_type]}** threshold set to {threshold} actions within {timeframe} seconds."
            )

    @antinuke_monitor.command(name="botkick")
    @app_commands.describe(enabled="Whether to automatically kick bots added by non-trusted users")
    async def monitor_botkick(self, ctx: commands.Context, enabled: bool) -> None:
        """Configure whether to automatically kick unauthorized bots."""
        guild = ctx.guild
        if not guild:
            return
        async with self.config.guild(guild).monitor() as monitor:
            if "bot_add" not in monitor:
                monitor["bot_add"] = DEFAULT_MONITOR_CONFIG.copy()
            monitor["bot_add"]["kick_bot"] = enabled

        if enabled:
            await ctx.send("✅ Auto-kick for unauthorized bots is now **enabled**.")
        else:
            await ctx.send("❌ Auto-kick for unauthorized bots is now **disabled**.")
