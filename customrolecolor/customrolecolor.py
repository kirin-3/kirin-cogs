from redbot.core import commands, Config, checks
import discord
import inspect

class CustomRoleColor(commands.Cog):
    """
    Allow admins to assign a role to a user, and let that user change the color, name, and icon of that role.
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
        Assign a role to a user for color, name, and icon management.
        Usage: [p]assignrole @user @role
        """
        if role >= ctx.guild.me.top_role:
            await ctx.send("I can't manage that role (it's higher than my top role).")
            return

        await self.config.guild(ctx.guild).assignments.set_raw(str(member.id), value=role.id)
        await ctx.send(f"{member.mention} can now manage the color, name, and icon of {role.mention}.")

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

        if not color.startswith("#") or len(color) != 7:
            await ctx.send("Please provide a valid hex color (e.g., #ff0000).")
            return

        try:
            new_color = discord.Color(int(color[1:], 16))
        except ValueError:
            await ctx.send("Invalid hex color.")
            return

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

    @commands.command()
    @commands.guild_only()
    async def myrolename(self, ctx, *, new_name: str):
        """
        Change the name of your assigned role.
        Usage: [p]myrolename New Role Name
        """
        assignments = await self.config.guild(ctx.guild).assignments()
        role_id = assignments.get(str(ctx.author.id))
        if not role_id:
            await ctx.send("You don't have a role assigned for name management.")
            return

        role = ctx.guild.get_role(role_id)
        if not role:
            await ctx.send("The assigned role no longer exists.")
            return

        if role >= ctx.guild.me.top_role:
            await ctx.send("I can't edit that role (it's higher than my top role).")
            return

        try:
            await role.edit(name=new_name, reason=f"Changed by {ctx.author}")
            await ctx.send(f"Changed name of your role to **{new_name}**.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to edit that role.")
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")

    @commands.command()
    @commands.guild_only()
    async def myroleicon(self, ctx):
        """
        Change the icon of your assigned role.
        Usage: [p]myroleicon (attach a PNG or JPEG image)
        """
        assignments = await self.config.guild(ctx.guild).assignments()
        role_id = assignments.get(str(ctx.author.id))
        if not role_id:
            await ctx.send("You don't have a role assigned for icon management.")
            return

        role = ctx.guild.get_role(role_id)
        if not role:
            await ctx.send("The assigned role no longer exists.")
            return

        if role >= ctx.guild.me.top_role:
            await ctx.send("I can't edit that role (it's higher than my top role).")
            return

        if "ROLE_ICONS" not in ctx.guild.features:
            await ctx.send("This server does not have the ROLE_ICONS feature (requires Level 2 boost).")
            return

        if not ctx.message.attachments:
            await ctx.send("Please attach a PNG or JPEG image to use as the role icon.")
            return

        attachment = ctx.message.attachments[0]
        if not attachment.filename.lower().endswith((".png", ".jpg", ".jpeg")):
            await ctx.send("The icon must be a PNG or JPEG image.")
            return

        if attachment.size > 256 * 1024:
            await ctx.send("The image must be under 256 KB.")
            return

        # Check if 'display_icon' is a valid argument for role.edit
        if "display_icon" not in inspect.signature(role.edit).parameters:
            await ctx.send("Role icons are not supported on this version of Redbot/discord.py.")
            return

        try:
            image_bytes = await attachment.read()
            await role.edit(display_icon=image_bytes, reason=f"Changed by {ctx.author}")
            await ctx.send(f"Changed icon for {role.mention}.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to edit that role.")
        except discord.HTTPException as e:
            await ctx.send(f"Failed to set icon: {e}")
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")

def setup(bot):
    bot.add_cog(CustomRoleColor())
