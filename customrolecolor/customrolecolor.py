from redbot.core import commands, Config, checks
import discord

class CustomRoleColor(commands.Cog):
    """
    Allow admins to assign a role to a user, and let that user change the color of that role.
    """

    def __init__(self):
        self.config = Config.get_conf(self, identifier=1234567890)
        # Structure: {guild_id: {user_id: role_id}}
        default_guild = {"assignments": {}}
        self.config.register_guild(**default_guild)

    @commands.command()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def assignrole(self, ctx, member: discord.Member, role: discord.Role):
        """
        Assign a role to a user for color management.
        Usage: [p]assignrole @user @role
        """
        # Optionally, check if the bot can manage the role
        if role >= ctx.guild.me.top_role:
            await ctx.send("I can't manage that role (it's higher than my top role).")
            return

        await self.config.guild(ctx.guild).assignments.set_raw(str(member.id), value=role.id)
        await ctx.send(f"{member.mention} can now manage the color of {role.mention}.")

    @commands.command()
    @commands.guild_only()
    async def myrolecolor(self, ctx, color: str):
        """
        Change the color of your assigned role.
        Usage: [p]myrolecolor #ff0000
        """
        assignments = await self.config.guild(ctx.guild).assignments()
        role_id = assignments.get(str(ctx.author.id))
        if not role_id:
            await ctx.send("You don't have a role assigned for color management.")
            return

        role = ctx.guild.get_role(role_id)
        if not role:
            await ctx.send("The assigned role no longer exists.")
            return

        # Validate color input
        if not color.startswith("#") or len(color) != 7:
            await ctx.send("Please provide a valid hex color (e.g., #ff0000).")
            return

        try:
            new_color = discord.Color(int(color[1:], 16))
        except ValueError:
            await ctx.send("Invalid hex color.")
            return

        # Check bot permissions and role hierarchy
        if role >= ctx.guild.me.top_role:
            await ctx.send("I can't edit that role (it's higher than my top role).")
            return

        try:
            await role.edit(color=new_color, reason=f"Changed by {ctx.author}")
            await ctx.send(f"Changed color of {role.mention} to {color}.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to edit that role.")
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")

def setup(bot):
    bot.add_cog(CustomRoleColor())
