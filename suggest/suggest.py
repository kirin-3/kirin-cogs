import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .migrations import migrate_global_schema
from .views import StickyView

log = logging.getLogger("red.kirin_cogs.suggest")

SUGGEST_CHANNEL_ID = 998190508847403060
UP_EMOJI_ID = 729330852747542568
DOWN_EMOJI_ID = 729330876114141215

UP_EMOJI_FALLBACK = "✅"
DOWN_EMOJI_FALLBACK = "❌"


def vote_emoji_kind(emoji: object) -> str | None:
    """Classify a vote reaction emoji as "up"/"down"/None.

    Recognizes both the configured custom emojis and the Unicode fallbacks
    used when the custom emojis are unavailable.
    """
    if isinstance(emoji, (discord.Emoji, discord.PartialEmoji)):
        if emoji.id == UP_EMOJI_ID:
            return "up"
        if emoji.id == DOWN_EMOJI_ID:
            return "down"
    elif isinstance(emoji, str):
        if emoji == UP_EMOJI_FALLBACK:
            return "up"
        if emoji == DOWN_EMOJI_FALLBACK:
            return "down"
    return None


@dataclass
class _LockEntry:
    """A keyed asyncio lock plus the number of coroutines holding or awaiting it."""

    lock: asyncio.Lock
    holders: int = 0


class Suggest(commands.Cog):
    """
    Suggestion system with sticky message and voting.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=2115656421364, force_registration=True)

        default_global = {
            "schema_version": 0,  # marker for migrations.py; 0 = legacy unmigrated record
            "next_id": 132,
            "sticky_message_id": None,
        }
        self.config.register_global(**default_global)

        self.config.init_custom("SUGGESTION", 1)  # suggestion_id
        self.config.register_custom(
            "SUGGESTION",
            author_id=0,
            content="",
            msg_id=0,
            status="pending",
            reason=None,
        )

        self.locked_channels: set[discord.TextChannel] = set()
        self._channel_cvs: dict[discord.TextChannel, asyncio.Condition] = {}
        # Per-guild identifier-allocation locks; idle entries are removed.
        self._id_locks: dict[int, _LockEntry] = {}
        self.bot.add_view(StickyView(self))

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Delete stored suggestions authored by a Discord user ID."""
        suggestions = await self.config.custom("SUGGESTION").all()
        if not isinstance(suggestions, dict):
            return
        for suggestion_id, data in suggestions.items():
            if isinstance(data, dict) and str(data.get("author_id")) == str(user_id):
                await self.config.custom("SUGGESTION", str(suggestion_id)).clear()

    @asynccontextmanager
    async def _id_lock(self, guild_id: int) -> AsyncGenerator[asyncio.Lock, None]:
        """Serialize suggestion identifier allocation within one guild.

        Registry entries are removed once no coroutine holds or awaits them,
        so the registry cannot grow unboundedly.
        """
        entry = self._id_locks.get(guild_id)
        if entry is None:
            entry = _LockEntry(asyncio.Lock())
            self._id_locks[guild_id] = entry
        entry.holders += 1
        try:
            async with entry.lock:
                yield entry.lock
        finally:
            entry.holders -= 1
            if entry.holders == 0 and self._id_locks.get(guild_id) is entry:
                del self._id_locks[guild_id]

    async def cog_load(self):
        await migrate_global_schema(self.config)
        # Ensure sticky message logic runs on reload if needed
        current_id = await self.config.next_id()
        if not isinstance(current_id, int) or isinstance(current_id, bool) or current_id < 132:
            await self.config.next_id.set(132)

    async def get_suggestion_channel(self) -> discord.TextChannel | None:
        channel = self.bot.get_channel(SUGGEST_CHANNEL_ID)
        return channel if isinstance(channel, discord.TextChannel) else None

    async def process_new_suggestion(self, interaction: discord.Interaction, content: str):
        channel = await self.get_suggestion_channel()
        if not channel:
            return await interaction.response.send_message("Suggestion channel not found.", ephemeral=True)

        # Allocate the identifier atomically per guild so concurrent
        # submissions can never share or overwrite an identifier.
        guild_id = channel.guild.id if channel.guild else 0
        async with self._id_lock(guild_id):
            s_id = await self.config.next_id()
            if not isinstance(s_id, int) or isinstance(s_id, bool) or s_id < 132:
                s_id = 132
            await self.config.next_id.set(s_id + 1)

        embed = discord.Embed(
            title=f"Suggestion #{s_id}", description=content, color=await self.bot.get_embed_color(channel)
        )
        embed.set_author(
            name=f"{interaction.user.display_name} ({interaction.user.id})",
            icon_url=interaction.user.display_avatar.url,
        )
        embed.set_footer(text="Pending Review")

        msg = await channel.send(embed=embed)

        # Add reactions
        try:
            up_emoji = self.bot.get_emoji(UP_EMOJI_ID) or UP_EMOJI_FALLBACK
            down_emoji = self.bot.get_emoji(DOWN_EMOJI_ID) or DOWN_EMOJI_FALLBACK
            await msg.add_reaction(up_emoji)
            await msg.add_reaction(down_emoji)
        except Exception as e:
            log.error(f"Failed to add reactions: {e}")

        async with self.config.custom("SUGGESTION", str(s_id)).all() as data:
            data["author_id"] = interaction.user.id
            data["content"] = content
            data["msg_id"] = msg.id
            data["status"] = "pending"

        await interaction.response.send_message("Suggestion submitted!", ephemeral=True)
        await self._maybe_repost_sticky(channel)

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.is_owner()
    async def approve(self, ctx, suggestion_id: int, *, reason: str | None = None):
        """Approve a suggestion."""
        await self._resolve_suggestion(ctx, suggestion_id, "approved", reason)

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.is_owner()
    async def reject(self, ctx, suggestion_id: int, *, reason: str | None = None):
        """Reject a suggestion."""
        await self._resolve_suggestion(ctx, suggestion_id, "rejected", reason)

    async def _resolve_suggestion(self, ctx, suggestion_id: int, status: str, reason: str | None):
        data = await self.config.custom("SUGGESTION", str(suggestion_id)).all()
        if not isinstance(data, dict):
            return await ctx.send("Suggestion not found.")

        # Validate the persisted shape before touching Discord state so
        # malformed or partial records fail safely and stay untouched.
        msg_id = data.get("msg_id")
        if not isinstance(msg_id, int) or isinstance(msg_id, bool) or not msg_id:
            return await ctx.send("Suggestion not found.")

        current_status = data.get("status")
        if not isinstance(current_status, str):
            return await ctx.send("Suggestion record is malformed; please ask an admin to review it.")

        if current_status != "pending":
            return await ctx.send(f"Suggestion is already {current_status}.")

        channel = await self.get_suggestion_channel()
        if not channel:
            return await ctx.send("Suggestion channel not found.")

        try:
            msg = await channel.fetch_message(msg_id)
        except discord.NotFound:
            return await ctx.send("Suggestion message not found.")

        if not msg.embeds:
            return await ctx.send(
                "The suggestion message is missing its embed; cannot resolve it safely. The record was left unchanged."
            )

        embed = msg.embeds[0]
        color = discord.Color.green() if status == "approved" else discord.Color.red()
        status_text = "Approved" if status == "approved" else "Rejected"

        embed.title = f"{status_text} Suggestion #{suggestion_id}"
        embed.color = color

        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)

        # Add result stats
        up_emoji = self.bot.get_emoji(UP_EMOJI_ID) or UP_EMOJI_FALLBACK
        down_emoji = self.bot.get_emoji(DOWN_EMOJI_ID) or DOWN_EMOJI_FALLBACK

        up_count = 0
        down_count = 0

        for reaction in msg.reactions:
            kind = vote_emoji_kind(reaction.emoji)
            if kind == "up":
                up_count = reaction.count - 1 if reaction.me else reaction.count
            elif kind == "down":
                down_count = reaction.count - 1 if reaction.me else reaction.count

        embed.add_field(name="Results", value=f"{up_emoji} {up_count} - {down_count} {down_emoji}", inline=False)
        embed.set_footer(text=f"{status_text}")

        await msg.edit(embed=embed)

        async with self.config.custom("SUGGESTION", str(suggestion_id)).all() as d:
            d["status"] = status
            d["reason"] = reason

        await ctx.tick()

        # Notify user
        try:
            author_id = data.get("author_id")
            if isinstance(author_id, int):
                user = await self.bot.fetch_user(author_id)
                if user:
                    await user.send(
                        f"Your suggestion #{suggestion_id} has been {status}!\nReason: {reason or 'No reason provided.'}"
                    )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.Member):
        if user.bot:
            return
        if reaction.message.channel.id != SUGGEST_CHANNEL_ID:
            return

        # Only voting reactions matter (custom emojis or Unicode fallbacks)
        added_kind = vote_emoji_kind(reaction.emoji)
        if added_kind is None:
            return

        # Ensure mutually exclusive
        msg = reaction.message
        for r in msg.reactions:
            if r.emoji == reaction.emoji:
                continue

            # Check if this other reaction is a voting emoji too
            if vote_emoji_kind(r.emoji) is not None:
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

        if isinstance(message.channel, discord.TextChannel):
            await self._maybe_repost_sticky(message.channel, responding_to_message=message)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if payload.channel_id != SUGGEST_CHANNEL_ID:
            return

        sticky_id = await self.config.sticky_message_id()
        if payload.message_id == sticky_id:
            channel = self.bot.get_channel(payload.channel_id)
            if isinstance(channel, discord.TextChannel):
                await self._maybe_repost_sticky(channel)

    async def _maybe_repost_sticky(
        self,
        channel: discord.TextChannel,
        responding_to_message: discord.Message | None = None,
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
                responding_to_message.id == sticky_id or responding_to_message.created_at < last_message_created_at
            ):
                return

            # Cooldown check
            try:
                utcnow = datetime.now(UTC)
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
                color=discord.Color.gold(),
            )
            new_sticky = await channel.send(embed=embed, view=view)
            await self.config.sticky_message_id.set(new_sticky.id)
        finally:
            self.locked_channels.remove(channel)
            cv.notify_all()
