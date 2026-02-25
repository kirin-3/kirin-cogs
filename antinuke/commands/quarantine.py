"""Quarantine management commands for the AntiNuke cog."""

import datetime
import discord
from redbot.core import commands, app_commands
from redbot.core.utils.chat_formatting import bold, inline, pagify

from ..constants import ACTION_NAMES


class AntiNukeQuarantineCommands(commands.Cog):
    """Quarantine management commands for AntiNuke."""

    @commands.group(name="antinuke", aliases=["an"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def antinuke(self, ctx: commands.Context) -> None:
        """AntiNuke configuration commands."""
        pass

    @antinuke.group(name="quarantine", aliases=["q"])
    async def antinuke_quarantine(self, ctx: commands.Context) -> None:
        """Manage quarantined users."""
        pass

    @antinuke_quarantine.command(name="list", aliases=["show"])
    async def quarantine_list(self, ctx: commands.Context) -> None:
        """Show all currently quarantined users."""
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

            # Show role count
            roles = data.get("roles", [])
            if roles:
                lines.append(f"- **Stored Roles:** {len(roles)} role(s)")

            lines.append("")

        text = "\n".join(lines)
        for page in pagify(text, page_length=2000):
            await ctx.send(page)

    @antinuke_quarantine.command(name="restore", aliases=["unquarantine", "unq"])
    @app_commands.describe(user="The user to restore")
    async def quarantine_restore(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Restore a quarantined user's roles.

        This will remove the quarantine role and restore their previous roles.
        """
        quarantined = await self.config.guild(ctx.guild).quarantined_users()

        if str(user.id) not in quarantined:
            await ctx.send(f"❌ {user.mention} is not quarantined.")
            return

        # Use the restore function from actions
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
    @app_commands.describe(user="The user to forcibly quarantine")
    @app_commands.describe(reason="Reason for the quarantine")
    async def quarantine_force(
        self, ctx: commands.Context, user: discord.Member, *, reason: str = "Manual quarantine"
    ) -> None:
        """Forcibly quarantine a user.

        This bypasses the trust system and immediately quarantines the user.
        Use with caution.
        """
        # Check hierarchy
        if ctx.guild.me.top_role <= user.top_role:
            await ctx.send(
                f"❌ Cannot quarantine {user.mention} - they have equal or higher roles."
            )
            return

        # Check if user is owner
        if user.id == ctx.guild.owner_id:
            await ctx.send("❌ Cannot quarantine the server owner.")
            return

        # Execute quarantine
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
    @app_commands.describe(user="The user to clear from quarantine records")
    async def quarantine_clear(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Clear a user from quarantine records without restoring roles.

        This removes the quarantine record but does not restore their roles.
        Useful if the user has left the server or you want to manage roles manually.
        """
        async with self.config.guild(ctx.guild).quarantined_users() as q_users:
            if str(user.id) not in q_users:
                await ctx.send(f"❌ {user.mention} is not in quarantine records.")
                return
            del q_users[str(user.id)]

        await ctx.send(
            f"✅ {user.mention} has been cleared from quarantine records."
        )

    @antinuke_quarantine.command(name="info")
    @app_commands.describe(user="The user to view quarantine info for")
    async def quarantine_info(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Show detailed quarantine information for a user."""
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
        embed.add_field(name="Trigger", value=bold(trigger), inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)

        embed.add_field(name="Quarantined At", value=timestamp, inline=False)

        # Show stored roles
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

    @antinuke_quarantine.command(name="restoreall")
    @commands.is_owner()
    async def quarantine_restoreall(self, ctx: commands.Context) -> None:
        """Restore all quarantined users.

        This is a dangerous operation and is restricted to the bot owner.
        """
        quarantined = await self.config.guild(ctx.guild).quarantined_users()

        if not quarantined:
            await ctx.send("No users are currently quarantined.")
            return

        count = 0
        failed = 0

        for user_id in list(quarantined.keys()):
            user = ctx.guild.get_member(int(user_id))
            if user:
                success = await self.quarantine_actions.restore_user(
                    ctx.guild, user, restored_by="restoreall"
                )
                if success:
                    count += 1
                else:
                    failed += 1

        await ctx.send(
            f"✅ Restored {count} user(s). Failed: {failed}."
        )

    @antinuke_quarantine.command(name="cleanup")
    async def quarantine_cleanup(self, ctx: commands.Context) -> None:
        """Clean up quarantine records for users who have left the server.

        This removes records for users who are no longer in the server.
        """
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
