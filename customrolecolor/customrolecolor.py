from redbot.core import commands, Config, checks
import discord
import inspect

class CustomRoleColor(commands.Cog):
    """
    Allow admins to assign a role to a user, and let that user change the color, name, and icon of that role.
    
    This cog enables server administrators to designate specific roles for users to customize.
    Once assigned, users can change the color, name, icon, and mentionable status of their role.
    
    Note: The bot must have manage roles permission and its top role must be above the roles being managed.
    """

    def __init__(self, bot):
        self.bot = bot
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
    async def myrolecolor(self, ctx, color: str, secondary_color: str = None):
        """
        Change the color of your assigned role.

        Usage:
        [p]myrolecolor #ff0000             (Flat color)
        [p]myrolecolor #ff0000 #00ff00     (Gradient color)
        [p]myrolecolor holographic         (Holographic style)
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

        if role >= ctx.guild.me.top_role:
            await ctx.send("I can't edit that role (it's higher than my top role).")
            return

        # Check for holographic preset
        if color.lower() == "holographic":
            try:
                await role.edit(
                    colour=discord.Colour(11127295),
                    secondary_colour=discord.Colour(16759788),
                    tertiary_colour=discord.Colour(16761760),
                    reason=f"Changed by {ctx.author}"
                )
                await ctx.send(f"Changed color of {role.mention} to holographic.")
            except discord.Forbidden:
                await ctx.send("I don't have permission to edit that role.")
            except Exception as e:
                await ctx.send(f"An error occurred: {e}")
            return

        # Helper to validate and parse hex color
        def parse_hex(c):
            if not c.startswith("#") or len(c) != 7:
                return None
            try:
                return discord.Color(int(c[1:], 16))
            except ValueError:
                return None

        primary_parsed = parse_hex(color)
        if not primary_parsed:
            await ctx.send("Please provide a valid hex color (e.g., #ff0000) or 'holographic'. You can use [this](https://htmlcolorcodes.com) site for getting the code.")
            return

        secondary_parsed = None
        if secondary_color:
            secondary_parsed = parse_hex(secondary_color)
            if not secondary_parsed:
                await ctx.send(f"Invalid secondary hex color: {secondary_color}")
                return

        try:
            # We explicitly set tertiary_colour to None to remove holographic effect if it was present
            # We set secondary_colour to None if not provided to remove gradient if it was present
            await role.edit(
                colour=primary_parsed,
                secondary_colour=secondary_parsed,
                tertiary_colour=None,
                reason=f"Changed by {ctx.author}"
            )
            if secondary_parsed:
                await ctx.send(f"Changed color of {role.mention} to gradient: {color} -> {secondary_color}.")
            else:
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
    async def myroleicon(self, ctx, emoji: str = None):
        """
        Change the icon of your assigned role.
        Usage:
          [p]myroleicon :emoji:         (set icon to a unicode emoji)
          [p]myroleicon                 (attach a PNG or JPEG image)
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

        # Check if 'display_icon' is a valid argument for role.edit
        if "display_icon" not in inspect.signature(role.edit).parameters:
            await ctx.send("Role icons are not supported on this version of Redbot/discord.py.")
            return

        # If an emoji is provided, use it as the icon
        if emoji:
            # Only allow unicode emoji, not custom Discord emoji
            if emoji.startswith("<:") or emoji.startswith("<a:"):
                await ctx.send("Only unicode emoji are supported as role icons, not custom Discord emoji.")
                return
            try:
                await role.edit(display_icon=emoji, reason=f"Changed by {ctx.author}")
                await ctx.send(f"Changed icon for {role.mention} to {emoji}")
            except discord.Forbidden:
                await ctx.send("I don't have permission to edit that role.")
            except discord.HTTPException as e:
                await ctx.send(f"Failed to set icon: {e}")
            except Exception as e:
                await ctx.send(f"An error occurred: {e}")
            return

        # Otherwise, check for an image attachment
        if not ctx.message.attachments:
            await ctx.send("Please attach a PNG or JPEG image, or provide a unicode emoji as an argument.")
            return

        attachment = ctx.message.attachments[0]
        if not attachment.filename.lower().endswith((".png", ".jpg", ".jpeg")):
            await ctx.send("The icon must be a PNG or JPEG image.")
            return

        if attachment.size > 256 * 1024:
            await ctx.send("The image must be under 256 KB.")
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

    @commands.command()
    @commands.guild_only()
    async def myrolementionable(self, ctx, state: str):
        """
        Toggle whether your assigned role is mentionable.
        Usage: [p]myrolementionable on
               [p]myrolementionable off
        """
        assignments = await self.config.guild(ctx.guild).assignments()
        role_id = assignments.get(str(ctx.author.id))
        if not role_id:
            await ctx.send("You don't have a role assigned for mention management.")
            return

        role = ctx.guild.get_role(role_id)
        if not role:
            await ctx.send("The assigned role no longer exists.")
            return

        if role >= ctx.guild.me.top_role:
            await ctx.send("I can't edit that role (it's higher than my top role).")
            return

        state = state.lower()
        if state not in ("on", "off", "true", "false", "yes", "no"):
            await ctx.send("Please specify `on` or `off`.")
            return

        mentionable = state in ("on", "true", "yes")
        try:
            await role.edit(mentionable=mentionable, reason=f"Changed by {ctx.author}")
            await ctx.send(f"{role.mention} is now {'mentionable' if mentionable else 'not mentionable'}.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to edit that role.")
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")

async def setup(bot):
    await bot.add_cog(CustomRoleColor(bot))
