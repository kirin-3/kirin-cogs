"""Remind a channel to bump the server on Disboard.

Ported from phenom4n4n's phen-cogs ``disboardreminder`` (MIT, Copyright (c) 2020-present
phenom4n4n), which is archived. It keeps the original Config identifier and cog name,
so the saved settings carry over.

Changes from the original:
- A bump is recognised by the image on Disboard's success embed, not the deprecated
  ``Message.interaction``, so it keeps working when discord.py removes that field.
- Messages use simple ``{member(mention)}``-style placeholders instead of TagScript,
  which dropped the TagScript, rapidfuzz and unidecode requirements. Embeds are gone.
- Missing channels or permissions are logged instead of silently clearing settings.
"""

import asyncio
import contextlib
import logging
import re
from datetime import UTC, datetime
from typing import Final

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

log = logging.getLogger("red.kirin-cogs.disboardreminder")

DISBOARD_BOT_ID: Final[int] = 302050872383242240
# Disboard's success embed always has this image, whatever language it replies in.
BUMP_IMAGE: Final[str] = "disboard.org/images/bot-command-image-bump.png"
BUMP_COOLDOWN: Final[int] = 2 * 60 * 60
LOCK_REASON: Final[str] = "DisboardReminder auto-lock"
PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"\{(member|server|guild)(?:\((\w+)\))?\}")

DEFAULT_GUILD: Final[dict] = {
    "channel": None,
    "role": None,
    "message": "It's been 2 hours since the last successful bump, could someone run </bump:947088344167366698>?",
    "tyMessage": "{member(mention)} thank you for bumping! Make sure to leave a review at <https://disboard.org/server/{guild(id)}>.",
    "nextBump": None,
    "lock": False,
    "clean": False,
}


def is_bump_success(message: discord.Message) -> bool:
    if message.author.id != DISBOARD_BOT_ID:
        return False
    return any(e.image.url and BUMP_IMAGE in e.image.url for e in message.embeds)


def render(template: str, guild: discord.Guild, member: discord.abc.User | None = None) -> str:
    """Fill ``{member}``, ``{member(mention)}``, ``{server(id)}`` and similar placeholders."""

    def replace(match: re.Match[str]) -> str:
        kind, attr = match.group(1), match.group(2)
        if kind == "member":
            if member is None:
                return ""
            values = {None: str(member), "mention": member.mention, "id": str(member.id), "name": member.display_name}
        else:
            values = {None: guild.name, "name": guild.name, "id": str(guild.id)}
        return values.get(attr, match.group(0))

    return PLACEHOLDER.sub(replace, template)[:2000]


class DisboardReminder(commands.Cog):
    """Set a reminder to bump on Disboard."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9765573181940385953309, force_registration=True)
        self.config.register_guild(**DEFAULT_GUILD)

    async def cog_load(self) -> None:
        self.reminder_loop.start()

    async def cog_unload(self) -> None:
        self.reminder_loop.cancel()

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Old versions kept per-member bump counts; drop the user's."""
        for guild_id, members in (await self.config.all_members()).items():
            if user_id in members:
                await self.config.member_from_ids(guild_id, user_id).clear()

    # --- reminders -----------------------------------------------------------

    @tasks.loop(seconds=30)
    async def reminder_loop(self) -> None:
        now = discord.utils.utcnow().timestamp()
        for guild_id, data in (await self.config.all_guilds()).items():
            next_bump = data.get("nextBump")
            if not isinstance(next_bump, int | float) or next_bump > now:
                continue
            guild = self.bot.get_guild(guild_id)
            if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
                continue
            try:
                await self.remind(guild, data)
            except Exception:
                log.exception("Bump reminder failed in %s", guild_id)

    @reminder_loop.before_loop
    async def _before_reminder_loop(self) -> None:
        await self.bot.wait_until_ready()

    async def remind(self, guild: discord.Guild, data: dict) -> None:
        # Clear first, so a failure below never makes the loop resend every 30 seconds.
        await self.config.guild(guild).nextBump.clear()
        channel = self._bump_channel(guild, data)
        if channel is None:
            return
        my_perms = channel.permissions_for(guild.me)
        if not my_perms.send_messages:
            log.warning("Cannot send the bump reminder in %s", channel.id)
            return
        if data.get("lock"):
            await self._set_lock(channel, locked=False)

        content = render(str(data.get("message") or DEFAULT_GUILD["message"]), guild)
        allowed_mentions = self.bot.allowed_mentions or discord.AllowedMentions.none()
        role = guild.get_role(data["role"]) if isinstance(data.get("role"), int) else None
        if role is not None:
            content = f"{role.mention}: {content}"[:2000]
            allowed_mentions = discord.AllowedMentions(roles=[role])
        await channel.send(content, allowed_mentions=allowed_mentions)

    # --- bump detection ----------------------------------------------------

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message) -> None:
        guild = message.guild
        if guild is None or message.author.id != DISBOARD_BOT_ID:
            return
        data = await self.config.guild(guild).all()
        bump_channel = self._bump_channel(guild, data)
        if bump_channel is None or await self.bot.cog_disabled_in_guild(self, guild):
            return

        if is_bump_success(message):
            await self.on_bump(message, guild, bump_channel, data)
        elif data.get("clean") and message.channel == bump_channel:
            if not bump_channel.permissions_for(guild.me).manage_messages:
                return
            await asyncio.sleep(2)
            with contextlib.suppress(discord.HTTPException):
                await message.delete()

    async def on_bump(
        self, message: discord.Message, guild: discord.Guild, bump_channel: discord.TextChannel, data: dict
    ) -> None:
        bump_time = message.created_at.timestamp()
        next_bump = data.get("nextBump")
        if isinstance(next_bump, int | float) and next_bump > bump_time:
            return  # a bump is already registered
        await self.config.guild(guild).nextBump.set(bump_time + BUMP_COOLDOWN)

        if bump_channel.permissions_for(guild.me).send_messages:
            member = message.interaction_metadata.user if message.interaction_metadata else None
            content = render(str(data.get("tyMessage") or DEFAULT_GUILD["tyMessage"]), guild, member)
            try:
                await bump_channel.send(content)
            except discord.HTTPException:
                log.warning("Could not send the bump thank-you in %s", bump_channel.id, exc_info=True)
        else:
            log.warning("Cannot send the bump thank-you in %s", bump_channel.id)

        if data.get("lock"):
            await self._set_lock(bump_channel, locked=True)

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _bump_channel(guild: discord.Guild, data: dict) -> discord.TextChannel | None:
        channel_id = data.get("channel")
        channel = guild.get_channel(channel_id) if isinstance(channel_id, int) else None
        return channel if isinstance(channel, discord.TextChannel) else None

    @staticmethod
    async def _set_lock(channel: discord.TextChannel, *, locked: bool) -> None:
        """Deny or reset @everyone's send permission, making sure the bot can still talk."""
        guild = channel.guild
        if not channel.permissions_for(guild.me).manage_roles:
            return
        try:
            mine = channel.overwrites_for(guild.me)
            if not mine.send_messages:
                mine.update(send_messages=True)
                await channel.set_permissions(guild.me, overwrite=mine, reason=LOCK_REASON)
            everyone = channel.overwrites_for(guild.default_role)
            target = False if locked else None
            if everyone.send_messages is not target:
                everyone.update(send_messages=target)
                await channel.set_permissions(guild.default_role, overwrite=everyone, reason=LOCK_REASON)
        except discord.HTTPException:
            log.warning("Could not %s bump channel %s", "lock" if locked else "unlock", channel.id, exc_info=True)

    # --- commands ------------------------------------------------------------

    @commands.group(aliases=["bprm"])  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def bumpreminder(self, ctx: commands.Context) -> None:
        """
        Set a reminder to bump on Disboard.

        The reminder is sent 2 hours after someone successfully bumps.
        """

    @bumpreminder.command(name="channel")
    async def bumpreminder_channel(self, ctx: commands.Context, channel: discord.TextChannel | None = None) -> None:
        """Set the bump reminder channel, or turn reminders off by leaving it out."""
        assert ctx.guild is not None
        if channel is None:
            await self.config.guild(ctx.guild).channel.clear()
            await ctx.send("Disabled bump reminders in this server.")
            return
        try:
            await channel.send(
                "Set this channel as the reminder channel for bumps. "
                "I will not send my first reminder until a successful bump is registered."
            )
        except discord.HTTPException:
            await ctx.send("I do not have permission to talk in that channel.")
            return
        await self.config.guild(ctx.guild).channel.set(channel.id)
        await ctx.tick()

    @bumpreminder.command(name="pingrole")
    @commands.has_permissions(mention_everyone=True)
    async def bumpreminder_pingrole(self, ctx: commands.Context, *, role: discord.Role | None = None) -> None:
        """Set a role to ping for bump reminders, or clear it by leaving it out."""
        assert ctx.guild is not None
        if role is None:
            await self.config.guild(ctx.guild).role.clear()
            await ctx.send("Cleared the role for bump reminders.")
            return
        await self.config.guild(ctx.guild).role.set(role.id)
        await ctx.send(f"Set {role.name} to ping for bump reminders.")

    @bumpreminder.command(name="thankyou", aliases=["ty"])
    async def bumpreminder_thankyou(self, ctx: commands.Context, *, message: str | None = None) -> None:
        """
        Change the thank-you message. Leave it out to reset it.

        Placeholders:
        `{member}`, `{member(mention)}`, `{member(id)}`, `{member(name)}` - who bumped
        `{server}`, `{server(id)}` - this server (`{guild}` works too)
        """
        assert ctx.guild is not None
        if message:
            await self.config.guild(ctx.guild).tyMessage.set(message)
            await ctx.tick()
        else:
            await self.config.guild(ctx.guild).tyMessage.clear()
            await ctx.send("Reset this server's Thank You message.")

    @bumpreminder.command(name="message")
    async def bumpreminder_message(self, ctx: commands.Context, *, message: str | None = None) -> None:
        """Change the reminder message. Leave it out to reset it. `{server}` placeholders work here."""
        assert ctx.guild is not None
        if message:
            await self.config.guild(ctx.guild).message.set(message)
            await ctx.tick()
        else:
            await self.config.guild(ctx.guild).message.clear()
            await ctx.send("Reset this server's reminder message.")

    @bumpreminder.command(name="clean")
    async def bumpreminder_clean(self, ctx: commands.Context, true_or_false: bool | None = None) -> None:
        """Toggle deleting Disboard's failed-bump messages in the bump channel."""
        assert ctx.guild is not None
        state = true_or_false if true_or_false is not None else not await self.config.guild(ctx.guild).clean()
        await self.config.guild(ctx.guild).clean.set(state)
        await ctx.send("I will now clean the bump channel." if state else "I will no longer clean the bump channel.")

    @bumpreminder.command(name="lock")
    @commands.has_permissions(manage_roles=True)
    async def bumpreminder_lock(self, ctx: commands.Context, true_or_false: bool | None = None) -> None:
        """Toggle locking the bump channel after a bump and unlocking it for the reminder."""
        assert ctx.guild is not None
        state = true_or_false if true_or_false is not None else not await self.config.guild(ctx.guild).lock()
        await self.config.guild(ctx.guild).lock.set(state)
        await ctx.send(
            "I will now auto-lock the bump channel." if state else "I will no longer auto-lock the bump channel."
        )

    @bumpreminder.command(name="settings")
    async def bumpreminder_settings(self, ctx: commands.Context) -> None:
        """Show the bump reminder settings."""
        assert ctx.guild is not None
        data = await self.config.guild(ctx.guild).all()
        channel = self._bump_channel(ctx.guild, data)
        role = ctx.guild.get_role(data["role"]) if isinstance(data.get("role"), int) else None
        embed = discord.Embed(
            color=await ctx.embed_color(),
            title="Bump Reminder Settings",
            description=(
                f"**Channel:** {channel.mention if channel else 'None'}\n"
                f"**Ping Role:** {role.mention if role else 'None'}\n"
                f"**Auto-lock:** {bool(data.get('lock'))}\n"
                f"**Clean Mode:** {bool(data.get('clean'))}"
            ),
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
        for key in ("message", "tyMessage"):
            embed.add_field(
                name=key, value=f"```{discord.utils.escape_markdown(str(data.get(key)))[:1000]}```", inline=False
            )
        next_bump = data.get("nextBump")
        if isinstance(next_bump, int | float):
            embed.timestamp = datetime.fromtimestamp(next_bump, UTC)
            embed.set_footer(text="Next bump registered for")
        await ctx.send(embed=embed)
