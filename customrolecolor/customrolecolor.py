from redbot.core import commands, Config, checks
import discord
import inspect
from PIL import Image, ImageDraw, ImageFont
import io
from functools import partial
import math

PALETTE_COLORS = [
    ("Red", "#FF0000"), ("Crimson", "#DC143C"), ("Tomato", "#FF6347"), ("Coral", "#FF7F50"),
    ("Pink", "#FFC0CB"), ("HotPink", "#FF69B4"), ("Magenta", "#FF00FF"), ("Maroon", "#800000"),
    ("Orange", "#FFA500"), ("Gold", "#FFD700"), ("Yellow", "#FFFF00"), ("Khaki", "#F0E68C"),
    ("Lime", "#00FF00"), ("Green", "#008000"), ("Forest", "#228B22"), ("Olive", "#808000"),
    ("Teal", "#008080"), ("Cyan", "#00FFFF"), ("SkyBlue", "#87CEEB"), ("Turquoise", "#40E0D0"),
    ("Blue", "#0000FF"), ("RoyalBlue", "#4169E1"), ("Navy", "#000080"), ("Indigo", "#4B0082"),
    ("Lavender", "#E6E6FA"), ("Purple", "#800080"), ("Violet", "#EE82EE"), ("Brown", "#A52A2A"),
    ("White", "#FFFFFF"), ("Silver", "#C0C0C0"), ("Grey", "#808080"), ("Black", "#000000")
]

def generate_palette_image():
    # Grid settings
    cols = 4
    rows = math.ceil(len(PALETTE_COLORS) / cols)
    cell_w, cell_h = 160, 80
    width = cols * cell_w
    height = rows * cell_h
    
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    
    try:
        # Try to load a nicer font if available, else default
        font = ImageFont.truetype("arial.ttf", 16)
    except IOError:
        font = ImageFont.load_default()
        
    for i, (name, hex_code) in enumerate(PALETTE_COLORS):
        row = i // cols
        col = i % cols
        x = col * cell_w
        y = row * cell_h
        
        # Draw color box
        rect_h = 50
        draw.rectangle([x + 5, y + 5, x + cell_w - 5, y + rect_h], fill=hex_code, outline="black")
        
        # Draw text
        text_fill = "black"
        draw.text((x + 10, y + rect_h + 8), f"{name} {hex_code}", fill=text_fill, font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

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
    @commands.cooldown(1, 10, commands.BucketType.user)
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
            c = c.strip("#")
            if len(c) != 6:
                return None
            try:
                return discord.Color(int(c, 16))
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
        except discord.HTTPException as e:
            await ctx.send(f"An error occurred: {e}")

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
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

        if not (1 <= len(new_name) <= 100):
            await ctx.send("Role name must be between 1 and 100 characters.")
            return

        try:
            await role.edit(name=new_name, reason=f"Changed by {ctx.author}")
            await ctx.send(f"Changed name of your role to **{new_name}**.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to edit that role.")
        except discord.HTTPException as e:
            await ctx.send(f"An error occurred: {e}")

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
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

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.user)
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
        except discord.HTTPException as e:
            await ctx.send(f"An error occurred: {e}")

    @commands.command()
    async def colorpreview(self, ctx, color: str):
        """
        Preview a color to see how it looks.
        Usage: [p]colorpreview #ff0000
        """
        c_clean = color.strip("#")
        if len(c_clean) != 6:
            await ctx.send("Please provide a valid hex color (e.g., #ff0000).")
            return
            
        try:
            parsed = discord.Color(int(c_clean, 16))
        except ValueError:
            await ctx.send("Invalid hex color.")
            return

        rgb = parsed.to_rgb()

        def _generate():
            image = Image.new("RGB", (150, 150), rgb)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            buffer.seek(0)
            return buffer

        try:
            file_buffer = await self.bot.loop.run_in_executor(None, _generate)
            filename = "preview.png"
            file = discord.File(file_buffer, filename=filename)
            embed = discord.Embed(title=f"Color Preview: {color}", color=parsed)
            embed.add_field(name="Hex", value=str(parsed))
            embed.add_field(name="RGB", value=str(rgb))
            embed.set_thumbnail(url=f"attachment://{filename}")
            await ctx.send(file=file, embed=embed)
        except Exception as e:
            await ctx.send(f"Failed to generate preview: {e}")

    @commands.command()
    async def colorpalette(self, ctx):
        """
        View a color palette to choose a color.
        """
        try:
            file_buffer = await self.bot.loop.run_in_executor(None, generate_palette_image)
            filename = "palette.png"
            file = discord.File(file_buffer, filename=filename)
            
            # Generate copyable text list
            desc_lines = []
            for name, hex_code in PALETTE_COLORS:
                desc_lines.append(f"`{hex_code}` **{name}**")
            
            description = "Here are some common colors. You can copy the code from the list below.\n\n" + " | ".join(desc_lines)
            
            # If description is too long (over 4096), we might need to truncate or split.
            # 32 colors * ~25 chars = ~800 chars. It fits easily.
            # Using " | " separator might be dense. Let's use newlines or grouped.
            # Newlines are easier to scan.
            description = "Here are some common colors. You can copy the code from the list below.\n\n" + "\n".join(desc_lines)
            
            # To save vertical space, maybe 2 columns? Embeds don't support columns in description.
            # Fields can work.
            
            embed = discord.Embed(title="Color Palette", description="Here are some common colors. You can copy the code from the list below.")
            embed.set_image(url=f"attachment://{filename}")
            
            # Add fields for text list to make it compact but copyable
            # Group into chunks of 8
            chunk_size = 8
            for i in range(0, len(PALETTE_COLORS), chunk_size):
                chunk = PALETTE_COLORS[i:i + chunk_size]
                value = "\n".join([f"`{code}` {name}" for name, code in chunk])
                embed.add_field(name="\u200b", value=value, inline=True)

            embed.add_field(name="More Colors", value="[HTML Color Codes](https://htmlcolorcodes.com)", inline=False)
            await ctx.send(file=file, embed=embed)
        except Exception as e:
            await ctx.send(f"Failed to generate palette: {e}")

async def setup(bot):
    await bot.add_cog(CustomRoleColor(bot))
