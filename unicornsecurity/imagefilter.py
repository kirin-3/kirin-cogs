import discord
from redbot.core import commands, Config
import re
import aiohttp

class ImageFilter(commands.Cog):
    """
    Delete non-tenor image links in a specific channel.
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
            r"https?://\S+\.discordapp\.\S+/attachments/\S+",  # Discord attachments
            r"https?://cdn\.discordapp\.\S+/attachments/\S+",  # Discord CDN
            r"https?://media\.discordapp\.\S+/attachments/\S+"  # Discord media
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
            async with aiohttp.ClientSession() as session:
                async with session.head(url, allow_redirects=True, timeout=5) as response:
                    content_type = response.headers.get("content-type", "")
                    return content_type.startswith("image/")
        except:
            return False  # If request fails, don't treat as image

    @commands.Cog.listener()
    async def on_message(self, message):
        """Listen for messages with image links that are not from tenor.com"""
        # Ignore bot messages
        if message.author.bot:
            return
            
        # Check if this is the targeted channel
        if not message.guild:
            return
            
        target_channel_id = await self.config.guild(message.guild).target_channel_id()
        if message.channel.id != target_channel_id:
            return
            
        # Get all URLs from the message
        content = message.content
        # Simple URL regex - find potential URLs
        url_pattern = re.compile(r'https?://\S+')
        urls = url_pattern.findall(content)
        
        # Also check message attachments
        attachment_urls = [attachment.url for attachment in message.attachments]
        all_urls = urls + attachment_urls
        
        # If no URLs or attachments, nothing to check
        if not all_urls:
            return
            
        # Check each URL
        for url in all_urls:
            # Skip tenor links
            if "tenor.com" in url:
                continue
                
            # Check if it's an image URL
            is_image = False
            
            # Check against patterns first for efficiency
            for pattern in self.compiled_patterns:
                if pattern.search(url):
                    is_image = True
                    break
                    
            # If not matched by pattern but could still be an image, check headers
            if not is_image and '.' in url.split('/')[-1]:
                is_image = await self.is_image_url(url)
                
            # If it's an image and not from tenor.com, delete the message
            if is_image:
                try:
                    await message.delete()
                    await message.channel.send(
                        f"{message.author.mention}, only Tenor GIFs are allowed in this channel. "
                        "Your message has been removed.",
                        delete_after=10
                    )
                except discord.Forbidden:
                    pass  # Bot doesn't have permission to delete
                except Exception as e:
                    print(f"Error deleting message: {e}")
                    
                # No need to check other URLs in this message since it's deleted
                break

    @commands.group()
    @commands.admin_or_permissions(administrator=True)
    async def imagefilter(self, ctx):
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
            description="Current settings for the Tenor-only image filter",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Target Channel",
            value=f"ID: {target_channel_id}\nName: {channel_name}",
            inline=False
        )
        embed.add_field(
            name="Filter Action",
            value="Delete non-tenor image links and send a warning message",
            inline=False
        )
        
        await ctx.send(embed=embed)

    @imagefilter.command(name="setchannel")
    @commands.admin_or_permissions(administrator=True)
    async def set_filter_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel for the Tenor-only filter.
        
        If no channel is specified, the current channel will be used.
        """
        channel = channel or ctx.channel
        
        await self.config.guild(ctx.guild).target_channel_id.set(channel.id)
        await ctx.send(f"Image filter will now monitor {channel.mention}.") 