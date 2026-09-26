import asyncio
import contextlib
import copy
import io
import json
import logging
import time
from datetime import timedelta
from typing import Any

import discord
from discord.ext import tasks
from redbot.core import Config, commands

from . import types as registry
from .engine import EMPTY, Counts, Event, Rule, Snapshot, compile_document, evaluate, fold, is_counted, plan
from .types import TRIGGERS, RuleError, validate

log = logging.getLogger("red.kirin_cogs.automod")

GUILD_ID = 684360255798509578
LOG_SIZE = 250
MAX_IMPORT = 2_000_000  # bytes


def empty_document() -> dict:
    return {"rulesets": [], "lists": [], "next_id": 1}


class AutoMod(commands.Cog):
    """Rule-based automod for Unicornia, managed on the staff site."""

    registry = registry  # the row type registry, for the staff site

    def __init__(self, bot) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x6175746F6D6F64, force_registration=True)
        self.config.register_global(rules=empty_document(), dry_run=True, log=[])
        self.snapshot: Snapshot = EMPTY
        self.counts = Counts()
        self.dry_run = True
        # Held across document() -> edit -> save() so concurrent editors can't overwrite each other.
        self.edit_lock = asyncio.Lock()
        self._log_lock = asyncio.Lock()
        self._renamed: dict[int, str] = {}  # member id -> nickname automod just set

    async def cog_load(self) -> None:
        self.dry_run = await self.config.dry_run()
        try:
            self.snapshot = compile_document(validate(await self.config.rules()))
        except Exception:
            log.exception("Stored automod rules are invalid; automod runs with no rules until they're fixed")
            self.snapshot = EMPTY
        self.sweep.start()

    async def cog_unload(self) -> None:
        self.sweep.cancel()

    @tasks.loop(minutes=10)
    async def sweep(self) -> None:
        self.counts.sweep(time.monotonic(), self.snapshot.window)

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Remove the user's action log entries and in-memory counts. Rules hold no user data."""
        self.counts.reset(user_id)
        async with self._log_lock:
            entries = await self.config.log()
            await self.config.log.set([e for e in entries if not isinstance(e, dict) or e.get("user_id") != user_id])

    # --- storage, used by the staff site --------------------------------------------------------

    async def document(self) -> dict:
        """A copy of the stored rules to edit and pass back to `save`."""
        return copy.deepcopy(await self.config.rules())

    async def save(self, document: object) -> dict:
        """Validate and store a whole rules document, then apply it from the next event. Raises RuleError.

        Callers hold `edit_lock` from the `document()` they edited through this save.
        """
        clean = validate(document)
        snapshot = compile_document(clean)
        await self.config.rules.set(clean)
        self.snapshot = snapshot
        return clean

    async def set_dry_run(self, value: bool) -> None:
        await self.config.dry_run.set(value)
        self.dry_run = value

    async def action_log(self) -> list[dict]:
        """Newest first."""
        return [e for e in reversed(await self.config.log()) if isinstance(e, dict)]

    async def _append_log(self, entry: dict) -> None:
        async with self._log_lock:
            entries = await self.config.log()
            entries.append(entry)
            await self.config.log.set(entries[-LOG_SIZE:])

    # --- events -----------------------------------------------------------------------------------

    def _member_ok(self, member: object) -> bool:
        return (
            isinstance(member, discord.Member)
            and member.guild.id == GUILD_ID
            and self.bot.user is not None
            and member.id != self.bot.user.id
        )

    def _message_ok(self, message: discord.Message) -> bool:
        return (
            message.guild is not None
            and message.webhook_id is None
            and not message.is_system()
            and self._member_ok(message.author)
        )

    @staticmethod
    def message_event(message: discord.Message, kind: str) -> Event:
        member = message.author
        assert isinstance(member, discord.Member)
        channel = message.channel
        channel_ids = {channel.id}
        if isinstance(channel, discord.Thread) and channel.parent_id:
            channel_ids.add(channel.parent_id)
        return Event(
            kind,
            member.id,
            is_bot=member.bot,
            role_ids=frozenset(r.id for r in member.roles),
            channel_ids=frozenset(channel_ids),
            channel_id=channel.id,
            text=fold(message.content),
            attachments=len(message.attachments),
            mentions=len(set(message.raw_mentions)) + len(set(message.raw_role_mentions)),
            at=time.monotonic(),
        )

    @staticmethod
    def member_event(member: discord.Member, kind: str) -> Event:
        names = (member.nick, member.global_name, member.name)
        return Event(
            kind,
            member.id,
            is_bot=member.bot,
            role_ids=frozenset(r.id for r in member.roles),
            names=tuple(fold(n) for n in names if n),
            at=time.monotonic(),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if self.snapshot.rules and self._message_ok(message):
            await self.handle(self.message_event(message, "message"), message.author, message)  # pyright: ignore[reportArgumentType]

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent) -> None:
        if payload.guild_id != GUILD_ID or not self.snapshot.rules:
            return
        message = payload.message
        # Link previews update the message without setting edited_at or changing the text.
        if message.edited_at is None:
            return
        if payload.cached_message is not None and payload.cached_message.content == message.content:
            return
        if not isinstance(message.author, discord.Member) and message.guild is not None:
            member = message.guild.get_member(message.author.id)
            if member is not None:
                message.author = member
        if self._message_ok(message):
            await self.handle(self.message_event(message, "edit"), message.author, message)  # pyright: ignore[reportArgumentType]

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if self.snapshot.rules and self._member_ok(member):
            await self.handle(self.member_event(member, "join"), member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.nick == after.nick or not self._member_ok(after):
            return
        if self._renamed.get(after.id) == after.nick:
            del self._renamed[after.id]  # automod's own rename
            return
        if self.snapshot.rules:
            await self.handle(self.member_event(after, "name"), after)

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User) -> None:
        if (before.name, before.global_name) == (after.name, after.global_name) or not self.snapshot.rules:
            return
        guild = self.bot.get_guild(GUILD_ID)
        member = guild.get_member(after.id) if guild else None
        if member is not None and self._member_ok(member):
            await self.handle(self.member_event(member, "name"), member)

    # --- evaluation and actions -------------------------------------------------------------------

    async def handle(self, event: Event, member: discord.Member, message: discord.Message | None = None) -> None:
        snapshot = self.snapshot
        history = self.counts.add(event, snapshot.window)
        hits = evaluate(snapshot, event, history, lambda role_id: member.guild.get_role(role_id) is not None)
        if not hits:
            return
        if any(is_counted(h.trigger) for h in hits):
            self.counts.reset(member.id)  # the same burst isn't punished again
        dry_run = self.dry_run
        actions = []
        for rule, effect in plan(hits, event):
            action = {"rule": f"{rule.ruleset} / {rule.name}", "type": effect["type"], "status": "would"}
            if not dry_run:
                try:
                    error = await self._run(rule, effect, member, message)
                except Exception as e:
                    log.exception("Automod %s failed for %s", effect["type"], member.id)
                    error = f"{type(e).__name__}: {e}"
                action["status"] = "done" if error is None else "skipped" if error == "" else "failed"
                if error:
                    action["error"] = error[:300]
            actions.append(action)
        await self._append_log(
            {
                "at": time.time(),
                "event": event.kind,
                "user_id": member.id,
                "user": str(member),
                "channel_id": event.channel_id or None,
                "rules": [
                    {"ruleset": h.rule.ruleset, "rule": h.rule.name, "trigger": TRIGGERS[h.trigger["type"]].label}
                    for h in hits
                ],
                "actions": actions,
                "dry_run": dry_run,
            }
        )

    async def _run(
        self, rule: Rule, effect: dict, member: discord.Member, message: discord.Message | None
    ) -> str | None:
        """Carry out one effect. Returns an error, "" when skipped, or None when done."""
        kind = effect["type"]
        guild = member.guild
        if kind == "delete":
            if message is None:
                return ""
            with contextlib.suppress(discord.NotFound):  # already gone
                await message.delete()
            return None
        if kind == "nickname":
            if member.nick == effect["nickname"]:
                return ""
            self._renamed[member.id] = effect["nickname"]
            try:
                await member.edit(nick=effect["nickname"], reason=f"Automod: {rule.ruleset} / {rule.name}")
            except discord.HTTPException:
                self._renamed.pop(member.id, None)
                raise
            return None
        if kind == "send":
            channel = guild.get_channel(effect["channel"]) if effect["channel"] else message and message.channel
            if not isinstance(channel, discord.abc.Messageable):
                return "The channel is missing."
            text = f"{member.mention} {effect['text']}" if effect["ping"] else effect["text"]
            mentions = discord.AllowedMentions(users=[member] if effect["ping"] else False)
            if effect["delete_after"]:
                await channel.send(text[:2000], delete_after=effect["delete_after"], allowed_mentions=mentions)
            else:
                await channel.send(text[:2000], allowed_mentions=mentions)
            return None

        moderation: Any = self.bot.get_cog("Moderation")
        if moderation is None:
            return "The moderation cog is not loaded."
        reason = effect["reason"] or f"Automod: {rule.ruleset} / {rule.name}"
        me = guild.me
        if kind == "warn":
            return await moderation.warn_member(member, reason, me)
        if kind == "mute":
            until = discord.utils.utcnow() + timedelta(minutes=effect["minutes"]) if effect["minutes"] else None
            return await moderation.mute_member(member, until, reason, me, keep_longer=True)
        if kind == "timeout":
            until = discord.utils.utcnow() + timedelta(minutes=effect["minutes"])
            return await moderation.timeout_member(member, until, reason, me)
        if kind == "ban":
            return await moderation.ban_user(guild, member, reason, effect["delete_days"], me)
        return f"Unknown effect {kind!r}."

    # --- commands ---------------------------------------------------------------------------------

    @commands.group()  # pyright: ignore[reportArgumentType]
    @commands.is_owner()
    async def automod(self, ctx: commands.Context) -> None:
        """Import and export automod rules. Edit them on the staff site."""

    @automod.command(name="import")  # pyright: ignore[reportArgumentType]
    async def automod_import(self, ctx: commands.Context) -> None:
        """Replace every ruleset and list with the attached JSON file. Export a backup first."""
        if not ctx.message.attachments:
            await ctx.send("Attach the rules JSON file to the command.")
            return
        attachment = ctx.message.attachments[0]
        if attachment.size > MAX_IMPORT:
            await ctx.send("That file is too big.")
            return
        try:
            data = json.loads(await attachment.read())
        except (ValueError, discord.HTTPException):
            await ctx.send("I couldn't read that file as JSON.")
            return
        try:
            async with self.edit_lock:
                document = await self.save(data)
        except RuleError as e:
            await ctx.send(f"Import failed, nothing changed. {e}")
            return
        note = ""
        if ctx.guild is not None:  # the file holds the word lists; don't leave it in a channel
            with contextlib.suppress(discord.HTTPException):
                await ctx.message.delete()
                note = " I deleted your message so the file isn't left in the channel."
        await ctx.send(
            f"Imported {len(document['rulesets'])} rulesets and {len(document['lists'])} lists. "
            f"Dry-run is {'on' if self.dry_run else 'off'}.{note}"
        )

    @automod.command(name="export")  # pyright: ignore[reportArgumentType]
    async def automod_export(self, ctx: commands.Context) -> None:
        """DM you every ruleset and list as a JSON file."""
        data = json.dumps(await self.config.rules(), indent=2, ensure_ascii=False).encode()
        try:
            await ctx.author.send(file=discord.File(io.BytesIO(data), "automod-rules.json"))
        except discord.HTTPException:
            await ctx.send("I couldn't DM you the file.")
            return
        if ctx.guild is not None:
            await ctx.send("Sent you the rules in DMs.")
