import math
import re
import time
from urllib.parse import urlsplit

import aiohttp
import discord
from redbot.core import Config, checks, commands

# Discord's upload limit for custom emojis
MAX_EMOJI_BYTES = 256 * 1024
# Seconds between one member's emoji changes, counted across the commands and the member site
COOLDOWN = 10
EMOJI_NAME = re.compile(r"[A-Za-z0-9_]{2,32}")
# Formats Discord accepts for emojis, by their first bytes rather than a filename
IMAGE_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=15)
# Only Discord's own CDN: an arbitrary URL would let users make the bot request internal addresses.
ALLOWED_IMAGE_HOSTS = frozenset({"cdn.discordapp.com", "media.discordapp.net"})


class CustomEmoji(commands.Cog):
    """
    Allows users with a specific role to create and manage their own custom emojis.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        default_guild = {
            "required_role_id": None,
            "user_limits": {},
            "emoji_ownership": {},  # {str(emoji_id): user_id}
        }
        self.config.register_guild(**default_guild)
        self._session: aiohttp.ClientSession | None = None
        self._cooldowns: dict[int, float] = {}  # user_id: monotonic time of their last change

    async def cog_unload(self) -> None:
        if self._session is not None:
            await self._session.close()

    def _get_session(self) -> aiohttp.ClientSession:
        # Red does not provide a shared HTTP session, so the cog owns one.
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT)
        return self._session

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Delete per-user limits and emoji ownership records."""
        user_key = str(user_id)
        for guild_id, data in (await self.config.all_guilds()).items():
            if not isinstance(data, dict):
                continue
            limits = data.get("user_limits", {})
            ownership = data.get("emoji_ownership", {})
            if not isinstance(limits, dict) or not isinstance(ownership, dict):
                continue
            limits.pop(user_key, None)
            limits.pop(user_id, None)
            ownership = {emoji_id: owner_id for emoji_id, owner_id in ownership.items() if str(owner_id) != user_key}
            group = self.config.guild_from_id(guild_id)
            await group.user_limits.set(limits)
            await group.emoji_ownership.set(ownership)

    async def get_user_limit(self, guild: discord.Guild, user_id: int) -> int:
        """Get the emoji limit for a specific user."""
        limits = await self.config.guild(guild).user_limits()
        return limits.get(str(user_id), 2)  # Default limit is 2

    async def get_live_ownership(self, guild: discord.Guild) -> dict[str, int]:
        """Return ownership records, first dropping those whose emoji no longer exists in the guild."""
        ownership = await self.config.guild(guild).emoji_ownership()
        stale = [emoji_id for emoji_id in ownership if guild.get_emoji(int(emoji_id)) is None]
        if stale:
            async with self.config.guild(guild).emoji_ownership() as stored:
                for emoji_id in stale:
                    stored.pop(emoji_id, None)
        return {emoji_id: owner_id for emoji_id, owner_id in ownership.items() if emoji_id not in stale}

    async def get_user_emoji_count(self, guild: discord.Guild, user_id: int) -> int:
        """Count how many existing emojis a user currently owns."""
        ownership = await self.get_live_ownership(guild)
        return sum(1 for owner_id in ownership.values() if owner_id == user_id)

    async def download_image(self, url: str) -> bytes:
        """Download an image from Discord's CDN, refusing anything over Discord's emoji size limit."""
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_IMAGE_HOSTS:
            raise ValueError("Only Discord image links are supported. Attach the image or use an existing emoji.")
        return await self._fetch(url)

    async def _fetch(self, url: str) -> bytes:
        too_large = f"Image is too large (max {MAX_EMOJI_BYTES // 1024}KB)."
        # No redirects: a CDN link must not bounce the request somewhere else.
        async with self._get_session().get(url, allow_redirects=False) as response:
            if response.status != 200:
                raise ValueError("Failed to download image.")
            if response.content_length is not None and response.content_length > MAX_EMOJI_BYTES:
                raise ValueError(too_large)
            # Content-Length can be missing or wrong, so enforce the cap while reading.
            data = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                data.extend(chunk)
                if len(data) > MAX_EMOJI_BYTES:
                    raise ValueError(too_large)
            return bytes(data)

    # --- Shared rules, used by the commands and the member site ---

    def _cooldown(self, user_id: int, *, stamp: bool) -> None:
        """Refuse within COOLDOWN of the member's last change; stamp now when asked.

        Synchronous, so a check-and-stamp can't interleave with another change.
        That also keeps two quick creates from both passing the slot check.
        """
        now = time.monotonic()
        last = self._cooldowns.get(user_id)
        if last is not None and now - last < COOLDOWN:
            wait = math.ceil(COOLDOWN - (now - last))
            raise ValueError(f"You're changing emojis too fast. Try again in {wait} second(s).")
        if stamp:
            self._cooldowns = {uid: t for uid, t in self._cooldowns.items() if now - t < COOLDOWN}
            self._cooldowns[user_id] = now

    @staticmethod
    def _check_name(name: str) -> None:
        if not EMOJI_NAME.fullmatch(name):
            raise ValueError("Emoji names should be 2 to 32 alphanumeric characters and underscores.")

    async def _require_role(self, member: discord.Member, action: str = "create") -> None:
        """Creating and renaming need the role set with `[p]ce setrole`, when one is set."""
        required_role_id = await self.config.guild(member.guild).required_role_id()
        if not required_role_id:
            return
        role = member.guild.get_role(required_role_id)
        if not role:
            raise ValueError(
                "The required role for creating emojis no longer exists. Please ask an admin to reconfigure it."
            )
        if role not in member.roles:
            raise ValueError(f"You do not have the required role to {action} emojis.")

    async def can_create(self, member: discord.Member) -> bool:
        try:
            await self._require_role(member)
        except ValueError:
            return False
        return True

    async def slots_for(self, member: discord.Member) -> tuple[int, int]:
        """(used, limit) for the member's emoji slots."""
        return (
            await self.get_user_emoji_count(member.guild, member.id),
            await self.get_user_limit(member.guild, member.id),
        )

    async def emojis_for(self, member: discord.Member) -> list[discord.Emoji]:
        ownership = await self.get_live_ownership(member.guild)
        return [
            emoji
            for emoji_id, owner_id in ownership.items()
            if owner_id == member.id and (emoji := member.guild.get_emoji(int(emoji_id)))
        ]

    async def _owns(self, member: discord.Member, emoji: discord.Emoji) -> bool:
        ownership = await self.config.guild(member.guild).emoji_ownership()
        return ownership.get(str(emoji.id)) == member.id

    async def create_emoji(self, member: discord.Member, name: str, image: bytes) -> discord.Emoji:
        """Create an emoji owned by the member, or raise ValueError with the reason."""
        guild = member.guild
        self._check_name(name)
        if len(image) > MAX_EMOJI_BYTES:
            raise ValueError(f"Image is too large (max {MAX_EMOJI_BYTES // 1024}KB).")
        if not image.startswith(IMAGE_SIGNATURES):
            raise ValueError("The image must be a PNG, JPEG or GIF.")
        self._cooldown(member.id, stamp=True)
        await self._require_role(member)
        used, limit = await self.slots_for(member)
        if used >= limit:
            raise ValueError(f"You have reached your limit of {limit} emojis.")
        try:
            emoji = await guild.create_custom_emoji(
                name=name, image=image, reason=f"Created by {member} ({member.id}) via CustomEmoji"
            )
        except discord.HTTPException as e:
            raise ValueError(f"Failed to create emoji. Discord error: {e}") from None
        async with self.config.guild(guild).emoji_ownership() as ownership:
            ownership[str(emoji.id)] = member.id
        return emoji

    async def rename_emoji(self, member: discord.Member, emoji: discord.Emoji, name: str) -> None:
        """Rename one of the member's own emojis, or raise ValueError."""
        self._check_name(name)
        await self._require_role(member, "rename")
        if not await self._owns(member, emoji):
            raise ValueError("You do not own this emoji.")
        self._cooldown(member.id, stamp=True)
        try:
            await emoji.edit(name=name, reason=f"Renamed by {member} via CustomEmoji")
        except discord.Forbidden:
            raise ValueError("I do not have permission to edit this emoji.") from None
        except discord.HTTPException as e:
            raise ValueError(f"Failed to edit emoji: {e}") from None

    async def delete_emoji(self, member: discord.Member, emoji: discord.Emoji) -> None:
        """Delete one of the member's own emojis, or raise ValueError."""
        if not await self._owns(member, emoji):
            raise ValueError("You do not own this emoji.")
        self._cooldown(member.id, stamp=True)
        await self._delete(emoji, member.guild, member)

    async def _delete(self, emoji: discord.Emoji, guild: discord.Guild, by: discord.abc.User) -> None:
        try:
            await emoji.delete(reason=f"Deleted by {by} via CustomEmoji")
        except discord.Forbidden:
            raise ValueError("I do not have permission to delete this emoji.") from None
        except discord.HTTPException as e:
            raise ValueError(f"Failed to delete emoji: {e}") from None
        async with self.config.guild(guild).emoji_ownership() as ownership:
            ownership.pop(str(emoji.id), None)

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: list[discord.Emoji],
        after: list[discord.Emoji],
    ) -> None:
        """Free the owner's slot as soon as an emoji is deleted, including through Discord directly."""
        removed = {str(emoji.id) for emoji in before} - {str(emoji.id) for emoji in after}
        if not removed:
            return
        ownership = await self.config.guild(guild).emoji_ownership()
        tracked = removed & ownership.keys()
        if not tracked:
            return
        async with self.config.guild(guild).emoji_ownership() as stored:
            for emoji_id in tracked:
                stored.pop(emoji_id, None)

    @commands.group(aliases=["ce"])
    @commands.guild_only()
    async def customemoji(self, ctx):
        """Manage custom emojis."""
        pass

    @customemoji.command(name="setrole")
    @checks.is_owner()
    async def ce_setrole(self, ctx, role: discord.Role | None = None):
        """
        Set the role required to create emojis.

        Leave empty to remove the requirement.
        """
        if role:
            await self.config.guild(ctx.guild).required_role_id.set(role.id)
            await ctx.send(f"Required role set to {role.name}.")
        else:
            await self.config.guild(ctx.guild).required_role_id.set(None)
            await ctx.send("Required role removed. Anyone can use this (subject to slot limits).")

    @customemoji.command(name="limit")
    @checks.is_owner()
    async def ce_limit(self, ctx, member: discord.Member, limit: int):
        """Set the emoji limit for a specific user."""
        if limit < 0:
            await ctx.send("Limit cannot be negative.")
            return

        async with self.config.guild(ctx.guild).user_limits() as limits:
            limits[str(member.id)] = limit
        await ctx.send(f"Set emoji limit for {member.display_name} to {limit}.")

    @customemoji.command(name="resetlimit")
    @checks.is_owner()
    async def ce_resetlimit(self, ctx, member: discord.Member):
        """Reset the emoji limit for a user to the default (2)."""
        async with self.config.guild(ctx.guild).user_limits() as limits:
            if str(member.id) in limits:
                del limits[str(member.id)]
                await ctx.send(f"Reset emoji limit for {member.display_name} to default.")
            else:
                await ctx.send(f"{member.display_name} does not have a custom limit.")

    @customemoji.command(name="create")
    @commands.bot_has_permissions(manage_emojis=True)
    async def ce_create(self, ctx, name: str, source: discord.PartialEmoji | str | None = None):
        """
        Create a new custom emoji.

        You can upload an image attachment or provide an existing emoji or Discord image link.
        Usage:
            [p]ce create my_emoji (with attachment)
            [p]ce create my_emoji <existing_emoji>
            [p]ce create my_emoji https://cdn.discordapp.com/attachments/...
        """
        try:
            # Checked before downloading too, so a refusal costs no download
            await self._require_role(ctx.author)
            current_count, limit = await self.slots_for(ctx.author)
            if current_count >= limit:
                raise ValueError(f"You have reached your limit of {limit} emojis.")
            self._cooldown(ctx.author.id, stamp=False)
            image_data = await self._command_image(ctx, source)
            emoji = await self.create_emoji(ctx.author, name, image_data)
        except ValueError as e:
            await ctx.send(str(e))
            return
        await ctx.send(
            f"Emoji {emoji} (`:{emoji.name}:`) created successfully! ({current_count + 1}/{limit} slots used)"
        )

    async def _command_image(self, ctx, source: discord.PartialEmoji | str | None) -> bytes:
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                raise ValueError("Invalid file type. Please upload a PNG, JPG, or GIF.")
            if attachment.size > MAX_EMOJI_BYTES:
                raise ValueError(f"Image is too large (max {MAX_EMOJI_BYTES // 1024}KB).")
            try:
                return await attachment.read()
            except Exception as e:
                raise ValueError(f"Failed to read attachment: {e}") from None
        if source:
            # download_image only accepts Discord CDN links
            url = source.url if isinstance(source, discord.PartialEmoji) else source
            try:
                return await self.download_image(str(url))
            except ValueError:
                raise
            except Exception as e:
                raise ValueError(f"Failed to download image from source: {e}") from None
        raise ValueError("Please provide an image attachment or a valid emoji/URL.")

    @customemoji.command(name="delete")
    @commands.bot_has_permissions(manage_emojis=True)
    async def ce_delete(self, ctx, emoji: discord.Emoji):
        """
        Delete a custom emoji.

        You can only delete emojis you own, unless you are a moderator.
        """
        try:
            if await self._owns(ctx.author, emoji):
                await self.delete_emoji(ctx.author, emoji)
            elif await self.bot.is_mod(ctx.author) or ctx.author.guild_permissions.manage_emojis:
                await self._delete(emoji, ctx.guild, ctx.author)
            else:
                raise ValueError("You do not own this emoji and do not have permission to delete it.")
        except ValueError as e:
            await ctx.send(str(e))
            return
        await ctx.send(f"Emoji `{emoji.name}` has been deleted.")

    @customemoji.command(name="rename")
    @commands.bot_has_permissions(manage_emojis=True)
    async def ce_rename(self, ctx, emoji: discord.Emoji, new_name: str):
        """
        Rename a custom emoji you own.

        Needs the same role as creating one.
        """
        try:
            await self.rename_emoji(ctx.author, emoji, new_name)
        except ValueError as e:
            await ctx.send(str(e))
            return
        await ctx.send(f"Emoji renamed to `:{new_name}:`.")

    @customemoji.command(name="list")
    async def ce_list(self, ctx, user: discord.Member | None = None):
        """
        List emojis owned by you or another user.
        """
        if user and user != ctx.author:
            # Check if requester is mod/admin if viewing someone else?
            # Plan says "If user arg provided (and requestor is Mod)"
            is_mod = await self.bot.is_mod(ctx.author)
            if not is_mod:
                await ctx.send("You can only view your own emojis.")
                return
        else:
            user = ctx.author

        assert user is not None

        ownership = await self.config.guild(ctx.guild).emoji_ownership()

        # Filter emojis for this user
        user_emoji_ids = [eid for eid, uid in ownership.items() if uid == user.id]

        if not user_emoji_ids:
            await ctx.send(f"{user.display_name} has no custom emojis.")
            return

        # Stale records are dropped as part of the lookup
        live_ownership = await self.get_live_ownership(ctx.guild)
        valid_emojis = [
            emoji for eid in user_emoji_ids if eid in live_ownership and (emoji := ctx.guild.get_emoji(int(eid)))
        ]

        if not valid_emojis:
            await ctx.send(f"{user.display_name} has no valid custom emojis (some may have been deleted manually).")
            return

        # Display
        limit = await self.get_user_limit(ctx.guild, user.id)
        title = f"Custom Emojis for {user.display_name} ({len(valid_emojis)}/{limit} slots)"

        description = "\n".join([f"{e} `:{e.name}:`" for e in valid_emojis])

        embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
        await ctx.send(embed=embed)
