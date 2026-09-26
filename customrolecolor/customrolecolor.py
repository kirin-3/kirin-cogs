import inspect
import io
import math
import time

import discord
from PIL import Image, ImageDraw, ImageFont
from redbot.core import Config, checks, commands

# Seconds between one member's role edits, counted across the commands and the member site
COOLDOWN = 10
MAX_ICON_BYTES = 256 * 1024
# PNG and JPEG, by their first bytes rather than a filename
ICON_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
# Discord's holographic role style: primary, secondary and tertiary colors
HOLOGRAPHIC = (11127295, 16759788, 16761760)


def _parse_hex(value: str) -> discord.Color | None:
    value = value.strip("#")
    if len(value) != 6:
        return None
    try:
        return discord.Color(int(value, 16))
    except ValueError:
        return None


PALETTE_COLORS = [
    ("Red", "#FF0000"),
    ("Crimson", "#DC143C"),
    ("Tomato", "#FF6347"),
    ("Coral", "#FF7F50"),
    ("Pink", "#FFC0CB"),
    ("HotPink", "#FF69B4"),
    ("Magenta", "#FF00FF"),
    ("Maroon", "#800000"),
    ("Orange", "#FFA500"),
    ("Gold", "#FFD700"),
    ("Yellow", "#FFFF00"),
    ("Khaki", "#F0E68C"),
    ("Lime", "#00FF00"),
    ("Green", "#008000"),
    ("Forest", "#228B22"),
    ("Olive", "#808000"),
    ("Teal", "#008080"),
    ("Cyan", "#00FFFF"),
    ("SkyBlue", "#87CEEB"),
    ("Turquoise", "#40E0D0"),
    ("Blue", "#0000FF"),
    ("RoyalBlue", "#4169E1"),
    ("Navy", "#000080"),
    ("Indigo", "#4B0082"),
    ("Lavender", "#E6E6FA"),
    ("Purple", "#800080"),
    ("Violet", "#EE82EE"),
    ("Brown", "#A52A2A"),
    ("White", "#FFFFFF"),
    ("Silver", "#C0C0C0"),
    ("Grey", "#808080"),
    ("Black", "#000000"),
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
    except OSError:
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
        self._cooldowns: dict[int, float] = {}  # user_id: monotonic time of their last edit

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Remove management-role associations for a Discord user ID."""
        for guild_id, data in (await self.config.all_guilds()).items():
            if not isinstance(data, dict):
                continue
            assignments = data.get("assignments", {})
            if isinstance(assignments, dict):
                removed = assignments.pop(str(user_id), None)
                removed = assignments.pop(user_id, removed)
                if removed is not None:
                    await self.config.guild_from_id(guild_id).assignments.set(assignments)

    def _preflight_role_edit(self, guild, role):
        if not guild.me.guild_permissions.manage_roles:
            return "I do not have the Manage Roles permission."
        if role.managed is True or role.is_default() is True:
            return "This role cannot be assigned or edited because it is a managed or default role."
        if role >= guild.me.top_role:
            return "I can't manage that role (it's higher than or equal to my top role)."
        return None

    # --- Shared rules, used by the commands and the member site ---

    def _cooldown(self, user_id: int) -> None:
        """Refuse within COOLDOWN of the member's last edit, else stamp now.

        Synchronous, so a check-and-stamp can't interleave with another edit.
        """
        now = time.monotonic()
        last = self._cooldowns.get(user_id)
        if last is not None and now - last < COOLDOWN:
            wait = math.ceil(COOLDOWN - (now - last))
            raise ValueError(f"You're editing your role too fast. Try again in {wait} second(s).")
        self._cooldowns = {uid: t for uid, t in self._cooldowns.items() if now - t < COOLDOWN}
        self._cooldowns[user_id] = now

    async def assigned_role(self, member: discord.Member) -> discord.Role | None:
        """The role assigned to the member with [p]assignrole, if it exists and they still hold it."""
        assignments = await self.config.guild(member.guild).assignments()
        role_id = assignments.get(str(member.id)) if isinstance(assignments, dict) else None
        if not isinstance(role_id, int):
            return None
        role = member.guild.get_role(role_id)
        if role is None or member.get_role(role.id) is None:
            return None
        return role

    async def _editable_role(self, member: discord.Member, purpose: str) -> discord.Role:
        """The member's assigned role, or ValueError saying why it can't be edited."""
        assignments = await self.config.guild(member.guild).assignments()
        if not isinstance(assignments, dict):
            assignments = {}
        role_id = assignments.get(str(member.id))
        if not isinstance(role_id, int):
            raise ValueError(f"You don't have a role assigned for {purpose} management.")
        role = member.guild.get_role(role_id)
        if role is None:
            raise ValueError("The assigned role no longer exists.")
        if member.get_role(role.id) is None:
            raise ValueError("You no longer have the role assigned for management.")
        error_msg = self._preflight_role_edit(member.guild, role)
        if error_msg:
            raise ValueError(error_msg)
        return role

    @staticmethod
    async def _edit(role: discord.Role, error_prefix: str = "An error occurred", **changes) -> None:
        try:
            await role.edit(**changes)
        except discord.Forbidden:
            raise ValueError("I don't have permission to edit that role.") from None
        except discord.HTTPException as e:
            raise ValueError(f"{error_prefix}: {e}") from None

    async def set_color(self, member: discord.Member, primary: str, secondary: str | None = None) -> discord.Role:
        """Set a flat color, or a gradient when `secondary` is given. Colors are hex like #ff0000."""
        role = await self._editable_role(member, "color")
        primary_parsed = _parse_hex(primary)
        if not primary_parsed:
            raise ValueError(
                "Please provide a valid hex color (e.g., #ff0000) or 'holographic'. You can use [this](https://htmlcolorcodes.com) site for getting the code."
            )
        secondary_parsed = None
        if secondary:
            secondary_parsed = _parse_hex(secondary)
            if not secondary_parsed:
                raise ValueError(f"Invalid secondary hex color: {secondary}")
        self._cooldown(member.id)
        # tertiary_colour=None removes a holographic style, secondary_colour=None a gradient
        await self._edit(
            role,
            colour=primary_parsed,
            secondary_colour=secondary_parsed,
            tertiary_colour=None,
            reason=f"Changed by {member}",
        )
        return role

    async def set_holographic(self, member: discord.Member) -> discord.Role:
        role = await self._editable_role(member, "color")
        self._cooldown(member.id)
        await self._edit(
            role,
            colour=discord.Colour(HOLOGRAPHIC[0]),
            secondary_colour=discord.Colour(HOLOGRAPHIC[1]),
            tertiary_colour=discord.Colour(HOLOGRAPHIC[2]),
            reason=f"Changed by {member}",
        )
        return role

    async def set_name(self, member: discord.Member, name: str) -> discord.Role:
        role = await self._editable_role(member, "name")
        if not (1 <= len(name) <= 100):
            raise ValueError("Role name must be between 1 and 100 characters.")
        self._cooldown(member.id)
        await self._edit(role, name=name, reason=f"Changed by {member}")
        return role

    async def set_icon(self, member: discord.Member, emoji: str | None, image: bytes | None) -> discord.Role:
        """Set the role icon to a unicode emoji, or to a PNG or JPEG image."""
        role = await self._editable_role(member, "icon")
        if "ROLE_ICONS" not in member.guild.features:
            raise ValueError("This server does not have the ROLE_ICONS feature (requires Level 2 boost).")
        # Check if 'display_icon' is a valid argument for role.edit
        if "display_icon" not in inspect.signature(role.edit).parameters:
            raise ValueError("Role icons are not supported on this version of Redbot/discord.py.")
        if emoji:
            # Only allow unicode emoji, not custom Discord emoji
            if emoji.startswith(("<:", "<a:")):
                raise ValueError("Only unicode emoji are supported as role icons, not custom Discord emoji.")
            icon: str | bytes = emoji
        elif image is not None:
            if len(image) > MAX_ICON_BYTES:
                raise ValueError("The image must be under 256 KB.")
            if not image.startswith(ICON_SIGNATURES):
                raise ValueError("The icon must be a PNG or JPEG image.")
            icon = image
        else:
            raise ValueError("Please attach a PNG or JPEG image, or provide a unicode emoji as an argument.")
        self._cooldown(member.id)
        await self._edit(role, "Failed to set icon", display_icon=icon, reason=f"Changed by {member}")
        return role

    async def set_mentionable(self, member: discord.Member, state: bool) -> discord.Role:
        role = await self._editable_role(member, "mention")
        self._cooldown(member.id)
        await self._edit(role, mentionable=state, reason=f"Changed by {member}")
        return role

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @checks.admin_or_permissions(manage_roles=True)
    async def assignrole(self, ctx, member: discord.Member, role: discord.Role):
        """
        Assign a role to a user for color, name, and icon management.
        Usage: [p]assignrole @user @role
        """
        error_msg = self._preflight_role_edit(ctx.guild, role)
        if error_msg:
            await ctx.send(error_msg)
            return

        if role not in member.roles:
            try:
                await member.add_roles(role, reason=f"Assigned via customrolecolor by {ctx.author}")
            except discord.Forbidden:
                await ctx.send("I don't have permission to add that role to the member.")
                return
            except discord.HTTPException as e:
                await ctx.send(f"An error occurred while adding the role: {e}")
                return

        await self.config.guild(ctx.guild).assignments.set_raw(str(member.id), value=role.id)  # type: ignore[reportAttributeAccessIssue]
        await ctx.send(f"{member.mention} can now manage the color, name, and icon of {role.mention}.")

    @commands.command()
    @commands.guild_only()
    async def myrolecolor(self, ctx, color: str, secondary_color: str | None = None):
        """
        Change the color of your assigned role.

        Usage:
        [p]myrolecolor #ff0000             (Flat color)
        [p]myrolecolor #ff0000 #00ff00     (Gradient color)
        [p]myrolecolor holographic         (Holographic style)
        """
        try:
            if color.lower() == "holographic":
                role = await self.set_holographic(ctx.author)
                await ctx.send(f"Changed color of {role.mention} to holographic.")
            elif secondary_color:
                role = await self.set_color(ctx.author, color, secondary_color)
                await ctx.send(f"Changed color of {role.mention} to gradient: {color} -> {secondary_color}.")
            else:
                role = await self.set_color(ctx.author, color)
                await ctx.send(f"Changed color of {role.mention} to {color}.")
        except ValueError as e:
            await ctx.send(str(e))

    @commands.command()
    @commands.guild_only()
    async def myrolename(self, ctx, *, new_name: str):
        """
        Change the name of your assigned role.
        Usage: [p]myrolename New Role Name
        """
        try:
            await self.set_name(ctx.author, new_name)
        except ValueError as e:
            await ctx.send(str(e))
            return
        await ctx.send(f"Changed name of your role to **{new_name}**.")

    @commands.command()
    @commands.guild_only()
    async def myroleicon(self, ctx, emoji: str | None = None):
        """
        Change the icon of your assigned role.
        Usage:
          [p]myroleicon :emoji:         (set icon to a unicode emoji)
          [p]myroleicon                 (attach a PNG or JPEG image)
        """
        try:
            image = None
            if not emoji and ctx.message.attachments:
                # Checked before downloading, so a refusal costs no download
                await self._editable_role(ctx.author, "icon")
                attachment = ctx.message.attachments[0]
                if not attachment.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                    raise ValueError("The icon must be a PNG or JPEG image.")
                if attachment.size > MAX_ICON_BYTES:
                    raise ValueError("The image must be under 256 KB.")
                try:
                    image = await attachment.read()
                except discord.HTTPException as e:
                    raise ValueError(f"Failed to set icon: {e}") from None
            role = await self.set_icon(ctx.author, emoji, image)
        except ValueError as e:
            await ctx.send(str(e))
            return
        await ctx.send(f"Changed icon for {role.mention} to {emoji}" if emoji else f"Changed icon for {role.mention}.")

    @commands.command()
    @commands.guild_only()
    async def myrolementionable(self, ctx, state: str):
        """
        Toggle whether your assigned role is mentionable.
        Usage: [p]myrolementionable on
               [p]myrolementionable off
        """
        state = state.lower()
        try:
            if state not in ("on", "off", "true", "false", "yes", "no"):
                # The role is checked first, so a member without one hears that instead
                await self._editable_role(ctx.author, "mention")
                raise ValueError("Please specify `on` or `off`.")
            mentionable = state in ("on", "true", "yes")
            role = await self.set_mentionable(ctx.author, mentionable)
        except ValueError as e:
            await ctx.send(str(e))
            return
        await ctx.send(f"{role.mention} is now {'mentionable' if mentionable else 'not mentionable'}.")

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

            # If description is too long (over 4096), we might need to truncate or split.
            # 32 colors * ~25 chars = ~800 chars. It fits easily.
            # Using " | " separator might be dense. Let's use newlines or grouped.
            # Newlines are easier to scan.
            # To save vertical space, maybe 2 columns? Embeds don't support columns in description.
            # Fields can work.

            embed = discord.Embed(
                title="Color Palette",
                description="Here are some common colors. You can copy the code from the list below.",
            )
            embed.set_image(url=f"attachment://{filename}")

            # Add fields for text list to make it compact but copyable
            # Group into chunks of 8
            chunk_size = 8
            for i in range(0, len(PALETTE_COLORS), chunk_size):
                chunk = PALETTE_COLORS[i : i + chunk_size]
                value = "\n".join([f"`{code}` {name}" for name, code in chunk])
                embed.add_field(name="\u200b", value=value, inline=True)

            embed.add_field(name="More Colors", value="[HTML Color Codes](https://htmlcolorcodes.com)", inline=False)
            await ctx.send(file=file, embed=embed)
        except Exception as e:
            await ctx.send(f"Failed to generate palette: {e}")


async def setup(bot):
    await bot.add_cog(CustomRoleColor(bot))
