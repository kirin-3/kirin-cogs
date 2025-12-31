import asyncio
import logging
from typing import Optional, Dict, Set
from datetime import datetime, timezone

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .views import StickyView

log = logging.getLogger("red.confess")

CONFESSION_CHANNEL_ID = 898576602441605120

class Confess(commands.Cog):
    """
    Confess your dirty sins.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=665235, force_registration=True)
        
        default_global = {
            "sticky_message_id": None,
        }
        self.config.register_global(**default_global)
        
        self.locked_channels: Set[discord.TextChannel] = set()
        self._channel_cvs: Dict[discord.TextChannel, asyncio.Condition] = {}
        self.bot.add_view(StickyView(self))

    async def get_confession_channel(self) -> Optional[discord.TextChannel]:
        return self.bot.get_channel(CONFESSION_CHANNEL_ID)

    async def process_confession(self, interaction: discord.Interaction, content: str):
        channel = await self.get_confession_channel()
        if not channel:
            return await interaction.response.send_message("Confession channel not found.", ephemeral=True)
            
        confession_content = f"**Anonymous Confession**\n>>> {discord.utils.escape_mentions(content)}"
        
        try:
            await channel.send(content=confession_content, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            return await interaction.response.send_message("I don't have permission to send messages to the confession room.", ephemeral=True)
        except Exception as e:
            log.error(f"Failed to send confession: {e}")
            return await interaction.response.send_message("Something went wrong.", ephemeral=True)
            
        await interaction.response.send_message("Your confession has been sent, you are forgiven now.", ephemeral=True)
        
        # Logging to bot owners
        log_embed = discord.Embed(
            title="New Confession Log",
            description=content,
            timestamp=datetime.now(timezone.utc),
            color=discord.Color.red()
        )
        log_embed.set_author(name=f"{interaction.user} ({interaction.user.id})", icon_url=interaction.user.display_avatar.url)
        log_embed.set_footer(text=f"Channel: {channel.name} ({channel.id})")

        owners = self.bot.owner_ids
        if not owners:
            try:
                info = await self.bot.application_info()
                owners = {info.owner.id}
            except Exception:
                owners = set()

        for owner_id in owners:
            try:
                owner = await self.bot.fetch_user(owner_id)
                if owner:
                    await owner.send(embed=log_embed)
            except Exception as e:
                log.error(f"Failed to send confession log to owner {owner_id}: {e}")

        await self._maybe_repost_sticky(channel)

    # Sticky Logic
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        if message.channel.id != CONFESSION_CHANNEL_ID:
            return
        
        await self._maybe_repost_sticky(message.channel, responding_to_message=message)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.channel_id != CONFESSION_CHANNEL_ID:
            return
        
        sticky_id = await self.config.sticky_message_id()
        if payload.message_id == sticky_id:
            channel = self.bot.get_channel(payload.channel_id)
            if channel:
                await self._maybe_repost_sticky(channel)

    async def _maybe_repost_sticky(
        self,
        channel: discord.TextChannel,
        responding_to_message: Optional[discord.Message] = None,
    ) -> None:
        cv = self._channel_cvs.setdefault(channel, asyncio.Condition())
        
        async with cv:
            await cv.wait_for(lambda: channel not in self.locked_channels)

            sticky_id = await self.config.sticky_message_id()
            if sticky_id is None:
                if channel.id != CONFESSION_CHANNEL_ID:
                    return
                await self._do_repost_sticky(channel, cv)
                return

            last_message_created_at = discord.utils.snowflake_time(sticky_id)
            if responding_to_message and (
                responding_to_message.id == sticky_id
                or responding_to_message.created_at < last_message_created_at
            ):
                return

            # Cooldown check
            try:
                utcnow = datetime.now(timezone.utc)
                last_msg_timestamp = discord.utils.snowflake_time(sticky_id)
                time_since = utcnow - last_msg_timestamp
                cooldown = 3
                time_to_wait = cooldown - time_since.total_seconds()
            except Exception:
                time_to_wait = 0
            
        if time_to_wait > 0:
            await asyncio.sleep(time_to_wait)

        async with cv:
            await cv.wait_for(lambda: channel not in self.locked_channels)
            # Re-check
            new_sticky_id = await self.config.sticky_message_id()
            if new_sticky_id != sticky_id:
                return 
            
            if channel.last_message_id == sticky_id:
                return

            await self._do_repost_sticky(channel, cv)

    async def _do_repost_sticky(self, channel: discord.TextChannel, cv: asyncio.Condition):
        self.locked_channels.add(channel)
        try:
            old_sticky_id = await self.config.sticky_message_id()
            
            if old_sticky_id:
                try:
                    msg = channel.get_partial_message(old_sticky_id)
                    await msg.delete()
                except discord.NotFound:
                    pass
                except Exception as e:
                    log.error(f"Failed to delete old sticky: {e}")

            view = StickyView(self)
            embed = discord.Embed(
                title="Have a Confession?",
                description="Click the button below to submit a new confession anonymously!",
                color=discord.Color.purple()
            )
            new_sticky = await channel.send(embed=embed, view=view)
            await self.config.sticky_message_id.set(new_sticky.id)
        finally:
            self.locked_channels.remove(channel)
            cv.notify_all()
