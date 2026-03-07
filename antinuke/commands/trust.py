"""Trust management commands for the AntiNuke cog."""

import discord
from typing import TYPE_CHECKING, Any
from redbot.core import commands, app_commands
from redbot.core.utils.chat_formatting import bold, inline, humanize_list

if TYPE_CHECKING:
    from redbot.core import Config
    from ..actions import QuarantineActions
    from ..utils import ActionCache


class AntiNukeTrustCommands(commands.Cog):
    """Trust management commands for AntiNuke."""
    config: "Config"
    action_cache: "ActionCache"
    quarantine_actions: "QuarantineActions"


    @commands.group(name="antinuke", aliases=["an"])  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def antinuke(self, ctx: commands.Context) -> None:
        """AntiNuke configuration commands."""
        pass

    @antinuke.group(name="trust", aliases=["trusted"])
    async def antinuke_trust(self, ctx: commands.Context) -> None:
        """Manage trusted users and roles.

        Trusted users bypass all AntiNuke monitoring.
        """
        pass

    @antinuke_trust.command(name="adduser")
    @app_commands.describe(user="The user to add to the trusted list")
    async def trust_adduser(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Add a user to the trusted list.

        Trusted users bypass all AntiNuke monitoring.
        The server owner is always trusted.
        """
        guild = ctx.guild
        if not guild:
            return
        if user.bot:
            await ctx.send("❌ Bots cannot be added to the trusted list.")
            return

        if user.id == guild.owner_id:
            await ctx.send("ℹ️ The server owner is always trusted by default.")
            return

        async with self.config.guild(guild).trusted_users() as trusted:
            if user.id in trusted:
                await ctx.send(f"❌ {user.mention} is already trusted.")
                return
            trusted.append(user.id)

        await ctx.send(f"✅ {user.mention} has been added to the trusted list.")

    @antinuke_trust.command(name="removeuser", aliases=["deluser", "rmuser"])
    @app_commands.describe(user="The user to remove from the trusted list")
    async def trust_removeuser(
        self, ctx: commands.Context, user: discord.Member
    ) -> None:
        """Remove a user from the trusted list."""
        guild = ctx.guild
        if not guild:
            return
        async with self.config.guild(guild).trusted_users() as trusted:
            if user.id not in trusted:
                await ctx.send(f"❌ {user.mention} is not in the trusted list.")
                return
            trusted.remove(user.id)

        await ctx.send(f"✅ {user.mention} has been removed from the trusted list.")

    @antinuke_trust.command(name="addrole")
    @app_commands.describe(role="The role to add to the trusted list")
    async def trust_addrole(
        self, ctx: commands.Context, role: discord.Role
    ) -> None:
        """Add a role to the trusted list.

        Anyone with this role will bypass all AntiNuke monitoring.
        """
        guild = ctx.guild
        if not guild:
            return
        if role.is_default():
            await ctx.send("❌ The @everyone role cannot be trusted.")
            return

        async with self.config.guild(guild).trusted_roles() as trusted:
            if role.id in trusted:
                await ctx.send(f"❌ {role.mention} is already trusted.")
                return
            trusted.append(role.id)

        await ctx.send(f"✅ {role.mention} has been added to the trusted roles.")

    @antinuke_trust.command(name="removerole", aliases=["delrole", "rmrole"])
    @app_commands.describe(role="The role to remove from the trusted list")
    async def trust_removerole(
        self, ctx: commands.Context, role: discord.Role
    ) -> None:
        """Remove a role from the trusted list."""
        guild = ctx.guild
        if not guild:
            return
        async with self.config.guild(guild).trusted_roles() as trusted:
            if role.id not in trusted:
                await ctx.send(f"❌ {role.mention} is not in the trusted list.")
                return
            trusted.remove(role.id)

        await ctx.send(f"✅ {role.mention} has been removed from the trusted roles.")

    @antinuke_trust.command(name="list", aliases=["show"])
    async def trust_list(self, ctx: commands.Context) -> None:
        """Show all trusted users and roles."""
        guild = ctx.guild
        if not guild:
            return
        trusted_users = await self.config.guild(guild).trusted_users()
        trusted_roles = await self.config.guild(guild).trusted_roles()

        lines = [
            "## 🔒 AntiNuke Trust List",
            "",
            f"**Note:** The server owner is always trusted.",
            "",
        ]

        # Trusted users
        if trusted_users:
            user_lines = []
            for user_id in trusted_users:
                user = guild.get_member(user_id)
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

        # Trusted roles
        if trusted_roles:
            role_lines = []
            for role_id in trusted_roles:
                role = guild.get_role(role_id)
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
        guild = ctx.guild
        if not guild:
            return
        await self.config.guild(guild).trusted_users.set([])
        await self.config.guild(guild).trusted_roles.set([])
        await ctx.send("✅ All trusted users and roles have been cleared.")
