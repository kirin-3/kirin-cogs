import logging

import discord
from redbot.core import app_commands, commands

log = logging.getLogger("red.kirin_cogs.verifyuser")


class VerifyUser(commands.Cog):
    """
    User Verification System

    Allows users with the authorized role to verify other users by granting them a verification role.
    """

    # Role IDs as constants
    AUTHORIZED_ROLE_ID = 898586656842600549
    VERIFICATION_ROLE_ID = 1267157222530748439

    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def _preflight_role_edit(
        guild: discord.Guild,
        actor: discord.Member,
        target: discord.Member,
        role: discord.Role,
    ) -> str | None:
        if not guild.me.guild_permissions.manage_roles:
            return "I do not have the Manage Roles permission."
        if role.managed is True or role.is_default() is True:
            return "This role cannot be assigned because it is a managed or default role."
        if role >= guild.me.top_role:
            return "I can't assign that role (it's higher than or equal to my top role)."
        if target.id == guild.me.id:
            return "I cannot verify myself."
        if target.bot:
            return "Bot accounts cannot be verified."
        if target.id == actor.id:
            return "You cannot use this command on yourself."
        if target.id == guild.owner_id:
            return "The server owner cannot be managed with this command."
        if target.top_role >= guild.me.top_role:
            return "I cannot manage that member because their top role is too high."
        if actor.id != guild.owner_id and target.top_role >= actor.top_role:
            return "You cannot manage a member with an equal or higher top role."
        return None

    @commands.hybrid_command(name="verifyuser")  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.bot_has_permissions(manage_roles=True)
    @app_commands.describe(target_user="The user to verify")
    async def verifyuser(self, ctx: commands.Context, target_user: discord.Member) -> None:
        """
        Verify a user by granting them the verification role.

        This command can only be used by users with the authorized role.

        Usage: [p]verifyuser @user
        """
        assert ctx.guild is not None
        assert isinstance(ctx.author, discord.Member)

        # Check if the command user has the required role
        authorized_role = ctx.guild.get_role(self.AUTHORIZED_ROLE_ID)
        if not authorized_role or authorized_role not in ctx.author.roles:
            await ctx.send("You don't have permission to use this command.", ephemeral=True)
            return

        # Get the verification role
        verification_role = ctx.guild.get_role(self.VERIFICATION_ROLE_ID)
        if not verification_role:
            await ctx.send("The verification role could not be found.", ephemeral=True)
            return

        # Check if the user already has the verification role
        if verification_role in target_user.roles:
            await ctx.send(f"{target_user.mention} is already verified.", ephemeral=True)
            return

        error_msg = self._preflight_role_edit(ctx.guild, ctx.author, target_user, verification_role)
        if error_msg:
            await ctx.send(error_msg, ephemeral=True)
            return

        # Assign the verification role
        try:
            await target_user.add_roles(verification_role, reason=f"Verified by {ctx.author}")
            await ctx.send(f"Successfully verified {target_user.mention}!")
        except discord.Forbidden:
            await ctx.send("I don't have permission to assign roles.", ephemeral=True)
        except discord.HTTPException:
            log.exception(
                "Discord failed to grant verification role %s to member %s in guild %s",
                verification_role.id,
                target_user.id,
                ctx.guild.id,
            )
            await ctx.send(
                "Discord could not assign the verification role. Please try again or contact an administrator.",
                ephemeral=True,
            )
        except Exception:
            log.exception("Unexpected verification failure for member %s", target_user.id)
            await ctx.send(
                "The verification operation failed unexpectedly. Please contact an administrator.", ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(VerifyUser(bot))
