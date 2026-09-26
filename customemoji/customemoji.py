from urllib.parse import urlsplit

import aiohttp
import discord
from redbot.core import Config, checks, commands

# Discord's upload limit for custom emojis
MAX_EMOJI_BYTES = 256 * 1024
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
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def ce_create(self, ctx, name: str, source: discord.PartialEmoji | str | None = None):
        """
        Create a new custom emoji.

        You can upload an image attachment or provide an existing emoji or Discord image link.
        Usage:
            [p]ce create my_emoji (with attachment)
            [p]ce create my_emoji <existing_emoji>
            [p]ce create my_emoji https://cdn.discordapp.com/attachments/...
        """
        guild = ctx.guild
        author = ctx.author

        # Check Role
        required_role_id = await self.config.guild(guild).required_role_id()
        if required_role_id:
            role = guild.get_role(required_role_id)
            if not role:
                await ctx.send(
                    "The required role for creating emojis no longer exists. Please ask an admin to reconfigure it."
                )
                return
            if role not in author.roles:
                await ctx.send("You do not have the required role to create emojis.")
                return

        # Check Limit
        limit = await self.get_user_limit(guild, author.id)
        current_count = await self.get_user_emoji_count(guild, author.id)

        if current_count >= limit:
            await ctx.send(f"You have reached your limit of {limit} emojis.")
            return

        # Determine Image Source
        image_data = None
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            if not attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
                await ctx.send("Invalid file type. Please upload a PNG, JPG, or GIF.")
                return
            if attachment.size > MAX_EMOJI_BYTES:
                await ctx.send(f"Image is too large (max {MAX_EMOJI_BYTES // 1024}KB).")
                return
            try:
                image_data = await attachment.read()
            except Exception as e:
                await ctx.send(f"Failed to read attachment: {e}")
                return
        elif source:
            url = None
            if isinstance(source, discord.PartialEmoji):
                url = source.url
            elif isinstance(source, str):
                url = source  # download_image only accepts Discord CDN links

            if url:
                try:
                    image_data = await self.download_image(str(url))
                except ValueError as e:
                    await ctx.send(f"{e}")
                    return
                except Exception as e:
                    await ctx.send(f"Failed to download image from source: {e}")
                    return

        if not image_data:
            await ctx.send("Please provide an image attachment or a valid emoji/URL.")
            return

        # Create Emoji
        try:
            emoji = await guild.create_custom_emoji(
                name=name, image=image_data, reason=f"Created by {author} ({author.id}) via CustomEmoji"
            )

            # Save Ownership
            async with self.config.guild(guild).emoji_ownership() as ownership:
                ownership[str(emoji.id)] = author.id

            await ctx.send(
                f"Emoji {emoji} (`:{emoji.name}:`) created successfully! ({current_count + 1}/{limit} slots used)"
            )

        except discord.HTTPException as e:
            await ctx.send(f"Failed to create emoji. Discord error: {e}")
        except Exception as e:
            await ctx.send(f"An unexpected error occurred: {e}")

    @customemoji.command(name="delete")
    @commands.bot_has_permissions(manage_emojis=True)
    async def ce_delete(self, ctx, emoji: discord.Emoji):
        """
        Delete a custom emoji.

        You can only delete emojis you own, unless you are a moderator.
        """
        ownership = await self.config.guild(ctx.guild).emoji_ownership()
        owner_id = ownership.get(str(emoji.id))

        is_mod = await self.bot.is_mod(ctx.author) or ctx.author.guild_permissions.manage_emojis
        is_owner = owner_id == ctx.author.id

        if not is_owner and not is_mod:
            await ctx.send("You do not own this emoji and do not have permission to delete it.")
            return

        try:
            await emoji.delete(reason=f"Deleted by {ctx.author} via CustomEmoji")

            async with self.config.guild(ctx.guild).emoji_ownership() as ownership:
                if str(emoji.id) in ownership:
                    del ownership[str(emoji.id)]

            await ctx.send(f"Emoji `{emoji.name}` has been deleted.")

        except discord.Forbidden:
            await ctx.send("I do not have permission to delete this emoji.")
        except discord.HTTPException as e:
            await ctx.send(f"Failed to delete emoji: {e}")

    @customemoji.command(name="rename")
    @commands.bot_has_permissions(manage_emojis=True)
    async def ce_rename(self, ctx, emoji: discord.Emoji, new_name: str):
        """
        Rename a custom emoji you own.
        """
        # Validate name (alphanumeric + underscores usually best for Discord)
        if not new_name.replace("_", "").isalnum():
            await ctx.send("Emoji names should only contain alphanumeric characters and underscores.")
            return

        ownership = await self.config.guild(ctx.guild).emoji_ownership()
        owner_id = ownership.get(str(emoji.id))

        if owner_id != ctx.author.id:
            await ctx.send("You do not own this emoji.")
            return

        try:
            await emoji.edit(name=new_name, reason=f"Renamed by {ctx.author} via CustomEmoji")
            await ctx.send(f"Emoji renamed to `:{new_name}:`.")
        except discord.Forbidden:
            await ctx.send("I do not have permission to edit this emoji.")
        except discord.HTTPException as e:
            await ctx.send(f"Failed to edit emoji: {e}")

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
