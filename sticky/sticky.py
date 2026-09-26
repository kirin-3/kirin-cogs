"""Sticky messages to the bottom of a channel.

Ported from Tobotimus' Tobo-Cogs ``sticky``. Like the original, this cog is licensed
GPL-3.0 (see LICENSE in this folder), unlike the rest of the repo. It keeps the original
Config identifier and cog name, so every channel's sticky message carries over.

Fixes over the original:
- Message deletes in DMs, threads and uncached channels crashed ``on_raw_message_delete``.
- Every message in every channel took a per-channel lock and a Config read; channels
  without a sticky now return after one Config read.
- A missing permission when reposting or deleting is logged instead of raising.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

import discord
from redbot.core import Config, commands
from redbot.core.utils.menus import start_adding_reactions
from redbot.core.utils.predicates import MessagePredicate, ReactionPredicate

log = logging.getLogger("red.kirin-cogs.sticky")

UNIQUE_ID = 0x6AFE8000  # the original's identifier; changing it orphans the saved stickies
DEFAULT_COOLDOWN = 3
HEADER = "__***Stickied Message***__"

StickyChannel = discord.TextChannel | discord.VoiceChannel | discord.Thread


def build_sticky(settings: dict[str, Any]) -> tuple[str | None, discord.Embed | None]:
    """Content and embed to send for a channel's settings."""
    header = settings.get("header_enabled", True)
    if settings.get("stickied") is not None:
        content = str(settings["stickied"])
        return (f"{HEADER}\n\n{content}" if header else content), None
    adv = settings.get("advstickied") or {}
    content = adv.get("content")
    embed = discord.Embed.from_dict(adv["embed"]) if adv.get("embed") else None
    if header:
        content = f"{HEADER}\n\n{content}" if content else HEADER
    return content, embed


def has_sticky(settings: dict[str, Any]) -> bool:
    adv = settings.get("advstickied") or {}
    return bool(settings.get("stickied") or adv.get("content") or adv.get("embed"))


class Sticky(commands.Cog):
    """Sticky messages to your channels."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.conf = Config.get_conf(self, identifier=UNIQUE_ID, force_registration=True)
        self.conf.register_channel(
            stickied=None,  # [p]sticky
            header_enabled=True,
            advstickied={"content": None, "embed": {}},  # [p]sticky existing
            last=None,
            cooldown=DEFAULT_COOLDOWN,
        )
        self.locked_channels: set[int] = set()
        self._channel_cvs: dict[int, asyncio.Condition] = {}

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """This cog stores no user data."""
        return

    # --- commands ------------------------------------------------------------

    @commands.group(invoke_without_command=True)  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.mod_or_permissions(manage_messages=True)
    async def sticky(self, ctx: commands.Context, *, content: str) -> None:
        """Sticky a message to this channel."""
        await self._set_sticky(ctx, stickied=content)

    @sticky.command(name="existing")
    async def sticky_existing(self, ctx: commands.Context, *, message_id_or_url: discord.Message) -> None:
        """Sticky an existing message to this channel.

        This will try to sticky the content and first embed of the message.
        Attachments will not be added to the stickied message.
        """
        message = message_id_or_url
        if not (message.content or message.embeds):
            await ctx.send("That message doesn't have any content or embed!")
            return
        embed = message.embeds[0].to_dict() if message.embeds else None
        await self._set_sticky(ctx, advstickied={"content": message.content or None, "embed": embed})

    @sticky.command(name="toggleheader")
    async def sticky_toggleheader(self, ctx: commands.Context, true_or_false: bool) -> None:
        """Toggle the header for stickied messages in this channel.

        The header is enabled by default.
        """
        await self.conf.channel(ctx.channel).header_enabled.set(true_or_false)  # pyright: ignore[reportArgumentType]
        await ctx.tick()

    @sticky.command(name="cooldown", aliases=["setcooldown"])
    async def sticky_cooldown(self, ctx: commands.Context, seconds: int | None = None) -> None:
        """Set how long to wait before reposting the sticky message in this channel.

        If no value is provided, resets to the default cooldown.
        The cooldown must be at least 3 seconds.
        """
        settings = self.conf.channel(ctx.channel)  # pyright: ignore[reportArgumentType]
        if seconds is None:
            await settings.cooldown.set(DEFAULT_COOLDOWN)
            await ctx.send(f"Cooldown has been reset to the default (**{DEFAULT_COOLDOWN} seconds**).")
            return
        if seconds < DEFAULT_COOLDOWN:
            await ctx.send(f"The cooldown cannot be set lower than **{DEFAULT_COOLDOWN} seconds**.")
            return
        await settings.cooldown.set(seconds)
        await ctx.tick()

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.mod_or_permissions(manage_messages=True)
    async def unsticky(self, ctx: commands.Context, force: bool = False) -> None:
        """Remove the sticky message from this channel.

        Do `[p]unsticky yes` to skip the confirmation prompt.
        """
        channel = ctx.channel
        settings = self.conf.channel(channel)  # pyright: ignore[reportArgumentType]
        async with self._lock_channel(channel.id):
            last_id = await settings.last()
            if last_id is None:
                await ctx.send("There is no stickied message in this channel.")
                return
            if not (force or await self._confirm_unsticky(ctx)):
                return
            data = await settings.all()
            # Keep the channel's header and cooldown settings.
            await settings.set({"header_enabled": data["header_enabled"], "cooldown": data["cooldown"]})
            with contextlib.suppress(discord.HTTPException):
                await channel.get_partial_message(last_id).delete()  # pyright: ignore[reportAttributeAccessIssue]
            await ctx.tick()

    async def _set_sticky(self, ctx: commands.Context, **sticky: Any) -> None:
        channel = ctx.channel
        assert isinstance(channel, StickyChannel)
        async with self.conf.channel(channel).all() as settings:  # pyright: ignore[reportArgumentType]
            settings.pop("stickied", None)
            settings.pop("advstickied", None)
            settings.update(sticky)
            content, embed = build_sticky(settings)
            msg = await channel.send(content, embed=embed or discord.utils.MISSING)
            if settings.get("last") is not None:
                with contextlib.suppress(discord.HTTPException):
                    await channel.get_partial_message(settings["last"]).delete()
            settings["last"] = msg.id

    # --- listeners -----------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Repost the sticky message below new messages."""
        channel = message.channel
        if message.guild is None or not isinstance(channel, StickyChannel):
            return
        if await self.conf.channel(channel).last() is None:  # pyright: ignore[reportArgumentType]
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        await self._maybe_repost(channel, responding_to=message, delete_last=True)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        """If the stickied message was deleted, re-post it."""
        if payload.guild_id is None:
            return
        channel = self.bot.get_channel(payload.channel_id)
        if not isinstance(channel, StickyChannel):
            return
        if payload.message_id != await self.conf.channel(channel).last():  # pyright: ignore[reportArgumentType]
            return
        await self._maybe_repost(channel)

    async def _maybe_repost(
        self,
        channel: StickyChannel,
        responding_to: discord.Message | None = None,
        *,
        delete_last: bool = False,
    ) -> None:
        cv = self._channel_cvs.setdefault(channel.id, asyncio.Condition())
        settings = self.conf.channel(channel)  # pyright: ignore[reportArgumentType]

        async with cv:
            await cv.wait_for(lambda: channel.id not in self.locked_channels)
            data = await settings.all()
            last_id = data["last"]
            if last_id is None:
                return
            last_message = channel.get_partial_message(last_id)
            # Don't respond to our own sticky, or to messages older than it.
            if responding_to and (responding_to.id == last_id or responding_to.created_at < last_message.created_at):
                return
            elapsed = (discord.utils.utcnow() - last_message.created_at).total_seconds()
            time_to_wait = data["cooldown"] - elapsed

        # Sleep outside the lock so unsticky isn't blocked.
        if time_to_wait > 0:
            await asyncio.sleep(time_to_wait)

        async with cv:
            await cv.wait_for(lambda: channel.id not in self.locked_channels)
            data = await settings.all()
            if data["last"] != last_id:
                return  # someone else reposted while we slept
            if not has_sticky(data):
                await settings.last.clear()
                return
            content, embed = build_sticky(data)
            try:
                new = await channel.send(content, embed=embed or discord.utils.MISSING)
            except discord.HTTPException:
                log.warning("Could not repost the sticky message in %s", channel.id, exc_info=True)
                return
            await settings.last.set(new.id)
            if delete_last:
                with contextlib.suppress(discord.HTTPException):
                    await last_message.delete()

    # --- helpers -------------------------------------------------------------

    @contextlib.asynccontextmanager
    async def _lock_channel(self, channel_id: int) -> AsyncIterator[None]:
        cv = self._channel_cvs.setdefault(channel_id, asyncio.Condition())
        async with cv:
            self.locked_channels.add(channel_id)
            try:
                yield
            finally:
                self.locked_channels.discard(channel_id)
                cv.notify_all()

    @staticmethod
    async def _confirm_unsticky(ctx: commands.Context) -> bool:
        question = "This will unsticky the current sticky message from this channel. Are you sure you want to do this?"
        if not ctx.channel.permissions_for(ctx.me).add_reactions:  # pyright: ignore[reportArgumentType]
            event = "message"
            msg = await ctx.send(f"{question} (y/n)")
            predicate = MessagePredicate.yes_or_no(ctx)
        else:
            event = "reaction_add"
            msg = await ctx.send(question)
            predicate = ReactionPredicate.yes_or_no(msg, ctx.author)
            start_adding_reactions(msg, ReactionPredicate.YES_OR_NO_EMOJIS)
        with contextlib.suppress(TimeoutError):
            await ctx.bot.wait_for(event, check=predicate, timeout=30)
        if not predicate.result:
            with contextlib.suppress(discord.HTTPException):
                await msg.delete()
        return bool(predicate.result)
