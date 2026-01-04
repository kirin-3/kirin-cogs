import aiohttp
import discord
import logging
import datetime
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from redbot.core import commands, Config
from discord.ext import tasks

log = logging.getLogger("red.kirin_cogs.dailyreddit")

class DailyReddit(commands.Cog):
    """
    Automated daily posting of the top image from specified subreddits.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=8473729101, force_registration=True)
        
        # Structure:
        # {
        #   "channels": {
        #       "channel_id_str": {
        #           "subreddit": "subreddit_name",
        #           "last_post_timestamp": 0.0
        #       }
        #   }
        # }
        default_guild = {
            "channels": {}
        }
        self.config.register_guild(**default_guild)
        
        self.session = aiohttp.ClientSession()
        self.daily_post_loop.start()

    def cog_unload(self):
        self.daily_post_loop.cancel()
        self.bot.loop.create_task(self.session.close())

    async def fetch_top_image(self, subreddit: str) -> Optional[str]:
        """
        Fetches the top image from the subreddit's 'top of day'.
        Returns URL if found, None otherwise.
        """
        url = f"https://www.reddit.com/r/{subreddit}/top.json?sort=top&t=day&limit=10"
        headers = {'User-Agent': 'Red-DiscordBot:DailyReddit:v1.0 (by /u/Kirin)'}
        
        try:
            async with self.session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    log.warning(f"Failed to fetch subreddit {subreddit}: Status {response.status}")
                    return None
                
                data = await response.json()
                
                if 'data' not in data or 'children' not in data['data']:
                    return None

                for post in data['data']['children']:
                    p = post['data']
                    
                    # Filter for images
                    is_image_hint = p.get('post_hint') == 'image'
                    
                    # Check extension cleanly
                    raw_url = p.get('url', '')
                    parsed = urlparse(raw_url)
                    path = parsed.path.lower()
                    has_image_ext = path.endswith(('.jpg', '.jpeg', '.png', '.gif'))
                    
                    if is_image_hint or has_image_ext:
                        return p['url']
                        
        except Exception as e:
            log.error(f"Error fetching from {subreddit}: {e}")
            return None
            
        return None

    @tasks.loop(hours=1)
    async def daily_post_loop(self):
        """
        Background loop to check for daily posts (runs hourly).
        """
        await self.bot.wait_until_ready()
        
        all_guilds = await self.config.all_guilds()
        now = datetime.datetime.now().timestamp()
        
        for guild_id, guild_data in all_guilds.items():
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
                
            channels_config = guild_data.get("channels", {})
            updates = {}
            
            for channel_id_str, data in channels_config.items():
                subreddit = data.get("subreddit")
                last_post = data.get("last_post_timestamp", 0)
                
                # Check if 20 hours have passed since last post
                if (now - last_post) < (20 * 60 * 60):
                    continue
                
                if not subreddit:
                    continue
                    
                channel = guild.get_channel(int(channel_id_str))
                if not channel:
                    continue
                    
                if not channel.permissions_for(guild.me).send_messages:
                    log.warning(f"Missing permissions in channel {channel.name} ({channel.id})")
                    continue

                image_url = await self.fetch_top_image(subreddit)
                
                if image_url:
                    try:
                        await channel.send(image_url)
                        # Mark to update timestamp
                        updates[channel_id_str] = now
                    except discord.HTTPException as e:
                        log.error(f"Failed to send message to {channel.id}: {e}")
                else:
                    log.info(f"No valid image found for r/{subreddit} today (Text-only or error).")
            
            # Save timestamp updates safely
            if updates:
                async with self.config.guild(guild).channels() as channels:
                    for cid, timestamp in updates.items():
                        if cid in channels:
                            channels[cid]["last_post_timestamp"] = timestamp

    @daily_post_loop.before_loop
    async def before_daily_post_loop(self):
        await self.bot.wait_until_ready()

    @commands.group(name="dailyreddit", aliases=["dr"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_channels=True)
    async def dailyreddit(self, ctx):
        """Manage DailyReddit subscriptions."""
        pass

    @dailyreddit.command(name="add")
    async def dailyreddit_add(self, ctx, subreddit: str, channel: discord.TextChannel = None):
        """
        Add a subreddit subscription to a channel.
        If no channel is specified, uses the current channel.
        """
        target_channel = channel or ctx.channel
        
        # Basic sanitization
        subreddit = subreddit.lstrip("r/")
        
        # Verify subreddit exists/is valid by doing a quick test fetch
        test_url = await self.fetch_top_image(subreddit)
        if test_url is None:
            # We don't block adding it, but we warn the user
            await ctx.send(f"⚠️ Warning: Could not fetch a valid image from `r/{subreddit}` right now. "
                           "It might be private, text-only, or invalid. I've added it anyway.")
        
        async with self.config.guild(ctx.guild).channels() as channels:
            # We use setdefault or simple assignment, but to avoid overwriting existing
            # keys if we add more in future, we could check. But here we *want* to overwrite
            # the subscription for this channel if it exists.
            channels[str(target_channel.id)] = {
                "subreddit": subreddit,
                "last_post_timestamp": 0 # Force post on next loop
            }
            
        await ctx.send(f"✅ `r/{subreddit}` will now post daily top images to {target_channel.mention}.")

    @dailyreddit.command(name="remove")
    async def dailyreddit_remove(self, ctx, channel: discord.TextChannel = None):
        """
        Remove the subscription from a channel.
        """
        target_channel = channel or ctx.channel
        channel_id = str(target_channel.id)
        
        async with self.config.guild(ctx.guild).channels() as channels:
            if channel_id in channels:
                del channels[channel_id]
                await ctx.send(f"✅ Removed DailyReddit subscription from {target_channel.mention}.")
            else:
                await ctx.send(f"❌ {target_channel.mention} does not have a configured subscription.")

    @dailyreddit.command(name="list")
    async def dailyreddit_list(self, ctx):
        """
        List all active subscriptions in this server.
        """
        channels_config = await self.config.guild(ctx.guild).channels()
        
        if not channels_config:
            return await ctx.send("No subscriptions configured in this server.")
            
        msg = "**DailyReddit Subscriptions:**\n"
        for channel_id, data in channels_config.items():
            channel = ctx.guild.get_channel(int(channel_id))
            channel_name = channel.mention if channel else f"<#{channel_id}> (Deleted)"
            subreddit = data.get("subreddit", "Unknown")
            last_ts = data.get("last_post_timestamp", 0)
            
            # Format timestamp nicely
            if last_ts > 0:
                last_post_str = f"<t:{int(last_ts)}:R>"
            else:
                last_post_str = "Never"
                
            msg += f"• {channel_name}: `r/{subreddit}` (Last post: {last_post_str})\n"
            
        await ctx.send(msg)

    @dailyreddit.command(name="test")
    async def dailyreddit_test(self, ctx, channel: discord.TextChannel = None):
        """
        Force an immediate fetch and post for a specific channel (or current).
        """
        target_channel = channel or ctx.channel
        channel_id = str(target_channel.id)
        
        channels_config = await self.config.guild(ctx.guild).channels()
        data = channels_config.get(channel_id)
        
        if not data:
            return await ctx.send(f"❌ {target_channel.mention} is not configured.")
            
        subreddit = data.get("subreddit")
        await ctx.send(f"🔎 Fetching top image from `r/{subreddit}`...")
        
        image_url = await self.fetch_top_image(subreddit)
        
        if image_url:
            await target_channel.send(image_url)
            if target_channel != ctx.channel:
                await ctx.send("✅ Posted.")
        else:
            await ctx.send(f"⚠️ No valid image found in the top 10 posts of `r/{subreddit}` today.")
