import ipaddress
import logging
import mimetypes
import re
import socket
from urllib.parse import urljoin, urlsplit

import aiohttp
import discord
from redbot.core import Config, commands

log = logging.getLogger("red.kirin_cogs.unicornsecurity.imagefilter")

URL_PATTERN = re.compile(r"https?://\S+")
SPOILER_PATTERN = re.compile(r"\|\|.+?\|\|", re.DOTALL)
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 3


def is_tenor_url(url: str) -> bool:
    """Whether the URL's actual host is tenor.com or one of its subdomains."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    return host is not None and (host == "tenor.com" or host.endswith(".tenor.com"))


def is_image_attachment(attachment: discord.Attachment) -> bool:
    """Discord sets the content type from the file; the filename covers an upload without one."""
    kind = attachment.content_type or mimetypes.guess_type(attachment.filename)[0] or ""
    return kind.startswith("image/")


def is_allowed_destination(url: str) -> bool:
    """Header probes only go to http(s) on public hosts; names are checked again once resolved."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True  # a name; _PublicResolver checks what it resolves to


class _PublicResolver(aiohttp.ThreadedResolver):
    """Refuses names that resolve to private, loopback, link-local or otherwise non-public addresses."""

    async def resolve(self, hostname: str, port: int = 0, family: int = socket.AF_INET):
        infos = await super().resolve(hostname, port, family)
        if not infos or not all(ipaddress.ip_address(info["host"]).is_global for info in infos):
            raise OSError(f"{hostname} does not resolve to a public address")
        return infos


class ImageFilter(commands.Cog):
    """
    Delete unspoilered non-tenor images in a specific channel.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567891, force_registration=True)

        # Default configuration
        default_guild = {
            "target_channel_id": 1319688029530492948  # The specific channel ID to monitor
        }
        self.config.register_guild(**default_guild)

        # Common image URL patterns
        self.image_patterns = [
            r"https?://\S+\.(?:png|jpg|jpeg|gif|webp|bmp|tiff|svg)(?:\?\S*)?",  # Direct image links
            r"https?://(?:i\.)?imgur\.com/\S+",  # Imgur
            r"https?://\S*?giphy\.com/\S+",  # Giphy
            r"https?://(?:i\.)?redd\.it/\S+",  # Reddit
            r"https?://\S+\.gfycat\.com/\S+",  # Gfycat
        ]

        # Compile patterns for better performance
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.image_patterns]

    async def is_image_url(self, url):
        """Check if a URL points to an image based on headers or patterns."""
        # First check against known patterns
        for pattern in self.compiled_patterns:
            if pattern.search(url):
                return True

        # If not matched by pattern, try content-type check
        try:
            return (await self._probe_content_type(url)).startswith("image/")
        except Exception:
            return False  # If request fails, don't treat as image

    async def _probe_content_type(self, url: str) -> str:
        """HEAD the URL, following redirects by hand so every hop is checked against is_allowed_destination."""
        connector = aiohttp.TCPConnector(resolver=_PublicResolver())
        async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=5)) as session:
            for _ in range(MAX_REDIRECTS + 1):
                if not is_allowed_destination(url):
                    return ""
                async with session.head(url, allow_redirects=False) as response:
                    location = response.headers.get("Location")
                    if response.status not in REDIRECT_STATUSES or not location:
                        return response.headers.get("content-type", "")
                url = urljoin(url, location)
        return ""

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages with unspoilered images that are not from tenor.com"""
        await self._check_message(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        """Edits can add image links too; embed-only updates (link previews) leave the content alone."""
        before = payload.cached_message
        after = payload.message
        if before is not None and before.content == after.content and before.attachments == after.attachments:
            return
        await self._check_message(after)

    async def _check_message(self, message: discord.Message) -> None:
        # Ignore bot messages
        if message.author.bot:
            return

        # Check if this is the targeted channel
        if not message.guild:
            return

        target_channel_id = await self.config.guild(message.guild).target_channel_id()
        if message.channel.id != target_channel_id:
            return

        if not await self._has_unspoilered_image(message):
            return
        try:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention}, images in this channel must be spoilered: wrap links in "
                "`||link||` or mark uploads as spoiler. Tenor GIFs are fine as they are. "
                "Your message has been removed.",
                delete_after=10,
            )
        except discord.Forbidden:
            pass  # Bot doesn't have permission to delete
        except discord.HTTPException:
            log.exception("Failed to delete a non-Tenor image message")

    async def _has_unspoilered_image(self, message: discord.Message) -> bool:
        if any(not a.is_spoiler() and is_image_attachment(a) for a in message.attachments):
            return True
        # Links outside ||spoiler|| tags; links without a file extension are checked by their headers
        for url in URL_PATTERN.findall(SPOILER_PATTERN.sub(" ", message.content)):
            if not is_tenor_url(url) and await self.is_image_url(url):
                return True
        return False

    @commands.group()  # type: ignore[arg-type]
    @commands.admin_or_permissions(administrator=True)
    async def imagefilter(self, ctx: commands.Context) -> None:
        """Image filter settings."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @imagefilter.command(name="status")
    @commands.admin_or_permissions(administrator=True)
    async def filter_status(self, ctx):
        """Show the current status of the image filter."""
        target_channel_id = await self.config.guild(ctx.guild).target_channel_id()
        channel = self.bot.get_channel(target_channel_id)
        channel_name = channel.name if channel else "Unknown channel"

        embed = discord.Embed(
            title="Image Filter Status",
            description="Current settings for the spoilered-images filter",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Target Channel", value=f"ID: {target_channel_id}\nName: {channel_name}", inline=False)
        embed.add_field(
            name="Filter Action",
            value="Delete unspoilered non-tenor images and send a warning message",
            inline=False,
        )

        await ctx.send(embed=embed)

    @imagefilter.command(name="setchannel")
    @commands.admin_or_permissions(administrator=True)
    async def set_filter_channel(self, ctx, channel: discord.TextChannel | None = None):
        """Set the channel for the spoilered-images filter.

        If no channel is specified, the current channel will be used.
        """
        channel = channel or ctx.channel

        await self.config.guild(ctx.guild).target_channel_id.set(channel.id)
        await ctx.send(f"Image filter will now monitor {channel.mention}.")
