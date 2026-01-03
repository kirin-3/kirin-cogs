import asyncio
import logging
from typing import Optional, Dict, Set
from datetime import datetime, timezone

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .views import StickyView

log = logging.getLogger("red.kirin_cogs.suggest")

SUGGEST_CHANNEL_ID = 998190508847403060
UP_EMOJI_ID = 729330852747542568
DOWN_EMOJI_ID = 729330876114141215

class Suggest(commands.Cog):
    """
    Suggestion system with sticky message and voting.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=2115656421364, force_registration=True)
        
        default_global = {
            "next_id": 132,
            "sticky_message_id": None,
        }
        self.config.register_global(**default_global)
        
        self.config.init_custom("SUGGESTION", 1) # suggestion_id
        self.config.register_custom(
            "SUGGESTION",
            author_id=0,
            content="",
            msg_id=0,
            status="pending",
            reason=None,
        )

        self.locked_channels: Set[discord.TextChannel] = set()
        self._channel_cvs: Dict[discord.TextChannel, asyncio.Condition] = {}
        self.bot.add_view(StickyView(self))

    async def cog_load(self):
        # Ensure sticky message logic runs on reload if needed
        current_id = await self.config.next_id()
        if current_id < 132:
            await self.config.next_id.set(132)

    async def get_suggestion_channel(self) -> Optional[discord.TextChannel]:
        return self.bot.get_channel(SUGGEST_CHANNEL_ID)

    async def process_new_suggestion(self, interaction: discord.Interaction, content: str):
        channel = await self.get_suggestion_channel()
        if not channel:
            return await interaction.response.send_message("Suggestion channel not found.", ephemeral=True)
            
        s_id = await self.config.next_id()
        await self.config.next_id.set(s_id + 1)
        
        embed = discord.Embed(
            title=f"Suggestion #{s_id}",
            description=content,
            color=await self.bot.get_embed_color(channel)
        )
        embed.set_author(name=f"{interaction.user.display_name} ({interaction.user.id})", icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text="Pending Review")
        
        msg = await channel.send(embed=embed)
        
        # Add reactions
        try:
            up_emoji = self.bot.get_emoji(UP_EMOJI_ID) or "✅"
            down_emoji = self.bot.get_emoji(DOWN_EMOJI_ID) or "❌"
            await msg.add_reaction(up_emoji)
            await msg.add_reaction(down_emoji)
        except Exception as e:
            log.error(f"Failed to add reactions: {e}")
            
        async with self.config.custom("SUGGESTION", s_id).all() as data:
            data["author_id"] = interaction.user.id
            data["content"] = content
            data["msg_id"] = msg.id
            data["status"] = "pending"
            
        await interaction.response.send_message("Suggestion submitted!", ephemeral=True)
        await self._maybe_repost_sticky(channel)

    @commands.command()
    @commands.is_owner()
    async def approve(self, ctx, suggestion_id: int, *, reason: Optional[str] = None):
        """Approve a suggestion."""
        await self._resolve_suggestion(ctx, suggestion_id, "approved", reason)

    @commands.command()
    @commands.is_owner()
    async def reject(self, ctx, suggestion_id: int, *, reason: Optional[str] = None):
        """Reject a suggestion."""
        await self._resolve_suggestion(ctx, suggestion_id, "rejected", reason)

    async def _resolve_suggestion(self, ctx, suggestion_id: int, status: str, reason: Optional[str]):
        data = await self.config.custom("SUGGESTION", suggestion_id).all()
        if not data["msg_id"]:
            return await ctx.send("Suggestion not found.")
            
        if data["status"] != "pending":
            return await ctx.send(f"Suggestion is already {data['status']}.")

        channel = await self.get_suggestion_channel()
        if not channel:
            return await ctx.send("Suggestion channel not found.")

        try:
            msg = await channel.fetch_message(data["msg_id"])
        except discord.NotFound:
            return await ctx.send("Suggestion message not found.")

        embed = msg.embeds[0]
        color = discord.Color.green() if status == "approved" else discord.Color.red()
        status_text = "Approved" if status == "approved" else "Rejected"
        
        embed.title = f"{status_text} Suggestion #{suggestion_id}"
        embed.color = color
        
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
            
        # Add result stats
        up_emoji = self.bot.get_emoji(UP_EMOJI_ID) or "✅"
        down_emoji = self.bot.get_emoji(DOWN_EMOJI_ID) or "❌"
        
        up_count = 0
        down_count = 0
        
        for reaction in msg.reactions:
            if str(reaction.emoji) == str(up_emoji):
                up_count = reaction.count - 1 if reaction.me else reaction.count
            elif str(reaction.emoji) == str(down_emoji):
                down_count = reaction.count - 1 if reaction.me else reaction.count
                
        embed.add_field(name="Results", value=f"{up_emoji} {up_count} - {down_count} {down_emoji}", inline=False)
        embed.set_footer(text=f"{status_text}")

        await msg.edit(embed=embed)
        
        async with self.config.custom("SUGGESTION", suggestion_id).all() as d:
            d["status"] = status
            d["reason"] = reason

        await ctx.tick()
        
        # Notify user
        try:
            user = await self.bot.fetch_user(data["author_id"])
            if user:
                await user.send(f"Your suggestion #{suggestion_id} has been {status}!\nReason: {reason or 'No reason provided.'}")
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.Member):
        if user.bot:
            return
        if reaction.message.channel.id != SUGGEST_CHANNEL_ID:
            return
            
        # Check if it's one of our custom emojis
        if not hasattr(reaction.emoji, "id"):
            return
            
        if reaction.emoji.id not in (UP_EMOJI_ID, DOWN_EMOJI_ID):
            return

        # Ensure mutually exclusive
        msg = reaction.message
        for r in msg.reactions:
            if r.emoji == reaction.emoji:
                continue
            
            # Check if this other reaction is one of our voting emojis
            if hasattr(r.emoji, "id") and r.emoji.id in (UP_EMOJI_ID, DOWN_EMOJI_ID):
                # Check if user reacted to this one too
                async for u in r.users():
                    if u.id == user.id:
                        await r.remove(user)

    # Sticky Logic
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        
        if message.channel.id != SUGGEST_CHANNEL_ID:
            return
        
        await self._maybe_repost_sticky(message.channel, responding_to_message=message)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.channel_id != SUGGEST_CHANNEL_ID:
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
                if channel.id != SUGGEST_CHANNEL_ID:
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
                title="Have a Suggestion?",
                description="Click the button below to submit a new suggestion!",
                color=discord.Color.gold()
            )
            new_sticky = await channel.send(embed=embed, view=view)
            await self.config.sticky_message_id.set(new_sticky.id)
        finally:
            self.locked_channels.remove(channel)
            cv.notify_all()
