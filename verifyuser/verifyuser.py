from redbot.core import commands
import discord


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

    @commands.command()
    @commands.guild_only()
    async def verifyuser(self, ctx, user_id: int):
        """
        Verify a user by granting them the verification role.
        
        This command can only be used by users with the authorized role.
        
        Usage: [p]verifyuser <user_id>
        """
        # Check if the command user has the required role
        authorized_role = ctx.guild.get_role(self.AUTHORIZED_ROLE_ID)
        if not authorized_role or authorized_role not in ctx.author.roles:
            await ctx.send("You don't have permission to use this command.")
            return

        # Get the verification role
        verification_role = ctx.guild.get_role(self.VERIFICATION_ROLE_ID)
        if not verification_role:
            await ctx.send("The verification role could not be found.")
            return

        # Get the target user
        try:
            target_user = await ctx.guild.fetch_member(user_id)
        except discord.NotFound:
            await ctx.send(f"User with ID `{user_id}` not found in this server.")
            return
        except discord.HTTPException:
            await ctx.send("An error occurred while fetching the user.")
            return

        # Check if the user already has the verification role
        if verification_role in target_user.roles:
            await ctx.send(f"{target_user.mention} is already verified.")
            return

        # Check bot permissions
        if verification_role >= ctx.guild.me.top_role:
            await ctx.send("I can't assign that role (it's higher than my top role).")
            return

        # Assign the verification role
        try:
            await target_user.add_roles(verification_role, reason=f"Verified by {ctx.author}")
            await ctx.send(f"Successfully verified {target_user.mention}!")
        except discord.Forbidden:
            await ctx.send("I don't have permission to assign roles.")
        except discord.HTTPException as e:
            await ctx.send(f"An error occurred while assigning the role: {e}")
        except Exception as e:
            await ctx.send(f"An unexpected error occurred: {e}")


async def setup(bot):
    await bot.add_cog(VerifyUser(bot))
