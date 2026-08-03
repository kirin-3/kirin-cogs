import asyncio
import dataclasses
import datetime
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

from .abc import CompositeMetaClass
from .commands import TicketCommands
from .common.constants import DEFAULT_GUILD, TicketState
from .common.functions import Functions
from .common.utils import (
    close_ticket,
    prune_invalid_tickets,
    ticket_owner_hastyped,
)
from .common.views import CloseView, PanelView
from .migrations import migrate_guild_schemas

log = logging.getLogger("red.kirin_cogs.tickets")


@dataclasses.dataclass
class _LockEntry:
    lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)
    holders: int = 0


class Tickets(TicketCommands, Functions, commands.Cog, metaclass=CompositeMetaClass):
    """
    Support ticket system with single-panel functionality
    """

    __author__ = "[vertyco](https://github.com/vertyco/vrt-cogs)"
    __version__ = "2.13.0"

    def format_help_for_context(self, ctx):
        helpcmd = super().format_help_for_context(ctx)
        info = f"{helpcmd}\nCog Version: {self.__version__}\nAuthor: {self.__author__}\n"
        return info

    async def red_delete_data_for_user(self, *, requester, user_id: int):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Delete ticket records and blacklist entries linked to a user ID."""
        user_key = str(user_id)
        for guild_id, data in (await self.config.all_guilds()).items():
            if not isinstance(data, dict):
                continue
            opened = data.get("opened", {})
            blacklist = data.get("blacklist", [])
            changed = False
            if isinstance(opened, dict):
                removed = opened.pop(user_key, None)
                removed = opened.pop(user_id, removed)
                changed = removed is not None
            if isinstance(blacklist, list) and any(str(value) == user_key for value in blacklist):
                blacklist = [value for value in blacklist if str(value) != user_key]
                changed = True
            if changed:
                group = self.config.guild_from_id(guild_id)
                await group.opened.set(opened)
                await group.blacklist.set(blacklist)

    def __init__(self, bot: Red):
        self.bot: Red = bot
        self.config = Config.get_conf(self, 117117, force_registration=True)
        self.config.register_guild(**DEFAULT_GUILD)

        # Cache
        self.valid = []  # Valid ticket channels
        self.views = []  # Saved views to end on reload
        self.view_cache: dict[int, list[discord.ui.View]] = {}  # Saved views to end on reload
        self.initializing = False
        self.startup_task: asyncio.Task | None = None

        # Per-guild/member creation locks prevent concurrent limit and record races.
        self._creation_locks: dict[tuple[int, int], _LockEntry] = {}
        # Per-guild ticket_num locks prevent numbering collisions
        self._num_locks: dict[int, _LockEntry] = {}

        self.auto_close.start()

    async def cog_load(self) -> None:
        await migrate_guild_schemas(self.config)
        self.startup_task = asyncio.create_task(self._startup())

    async def cog_unload(self) -> None:
        if self.startup_task:
            self.startup_task.cancel()
        for view in self.views:
            view.stop()
        self.auto_close.cancel()

    @asynccontextmanager
    async def _creation_lock(self, guild_id: int, member_id: int) -> AsyncGenerator[asyncio.Lock, None]:
        """Serialize ticket reservations for one member in one guild."""
        key = (guild_id, member_id)
        entry = self._creation_locks.get(key)
        if entry is None:
            entry = _LockEntry()
            self._creation_locks[key] = entry
        entry.holders += 1
        try:
            async with entry.lock:
                yield entry.lock
        finally:
            entry.holders -= 1
            if entry.holders == 0 and self._creation_locks.get(key) is entry:
                del self._creation_locks[key]

    @asynccontextmanager
    async def _num_lock(self, guild_id: int) -> AsyncGenerator[asyncio.Lock, None]:
        """Per-guild lock for ticket_num allocation."""
        entry = self._num_locks.get(guild_id)
        if entry is None:
            entry = _LockEntry()
            self._num_locks[guild_id] = entry
        entry.holders += 1
        try:
            async with entry.lock:
                yield entry.lock
        finally:
            entry.holders -= 1
            if entry.holders == 0 and self._num_locks.get(guild_id) is entry:
                del self._num_locks[guild_id]

    async def _startup(self) -> None:
        await self.bot.wait_until_red_ready()
        await self._import_settings()
        await asyncio.sleep(6)
        await self._reconcile_stale_tickets()
        await self.initialize()

    async def _reconcile_stale_tickets(self) -> None:
        """Clean up tickets left in non-terminal states after a restart.

        - PENDING tickets with no channel -> remove the record
        - PENDING tickets with a channel -> promote to ACTIVE
        - CLOSE_PENDING / CLOSE_FAILED tickets -> attempt channel deletion again
        """
        all_guilds = await self.config.all_guilds()
        for gid, data in all_guilds.items():
            guild = self.bot.get_guild(gid)
            if not guild:
                continue
            opened = data.get("opened", {})
            if not opened:
                continue

            modified = False
            users_to_remove: list[str] = []
            tickets_to_remove: list[tuple[str, str]] = []
            tickets_to_promote: list[tuple[str, str, str]] = []

            for uid, tickets in opened.items():
                for cid, ticket in tickets.items():
                    state = ticket.get("state", TicketState.ACTIVE)
                    raw_channel_id = ticket.get("channel_id") if state == TicketState.PENDING else cid
                    try:
                        channel_id = int(raw_channel_id) if raw_channel_id else None
                    except (TypeError, ValueError):
                        channel_id = None
                    channel = guild.get_channel_or_thread(channel_id) if channel_id else None
                    if channel is None and state == TicketState.PENDING:
                        token = ticket.get("reconcile_token")
                        if isinstance(token, str) and token:
                            channel = discord.utils.find(
                                lambda candidate, expected=token: candidate.topic == expected,
                                guild.text_channels,
                            )

                    if state == TicketState.PENDING:
                        if channel is None:
                            # Channel never created or was deleted
                            tickets_to_remove.append((uid, cid))
                        else:
                            # Channel exists, promote and replace the placeholder key.
                            tickets_to_promote.append((uid, cid, str(channel.id)))

                    elif state in (TicketState.CLOSE_PENDING, TicketState.CLOSE_FAILED):
                        if channel is None:
                            # Channel already gone, just remove record
                            tickets_to_remove.append((uid, cid))
                        else:
                            # Try to delete the channel again
                            try:
                                await channel.delete(reason="Reconciling stale close-pending ticket")
                                tickets_to_remove.append((uid, cid))
                            except discord.Forbidden:
                                log.warning(
                                    f"Cannot delete close-failed ticket channel {cid} in {guild.name}: missing perms"
                                )
                            except discord.HTTPException as e:
                                log.warning(f"Failed to delete close-failed ticket channel {cid} in {guild.name}: {e}")

            if tickets_to_remove or tickets_to_promote:
                async with self.config.guild(guild).opened() as opened_conf:
                    for uid, cid in tickets_to_remove:
                        if uid in opened_conf and cid in opened_conf[uid]:
                            del opened_conf[uid][cid]
                            if not opened_conf[uid]:
                                users_to_remove.append(uid)
                            modified = True

                    for uid in users_to_remove:
                        if uid in opened_conf:
                            del opened_conf[uid]

                    for uid, cid, channel_id in tickets_to_promote:
                        if uid in opened_conf and cid in opened_conf[uid]:
                            ticket = opened_conf[uid].pop(cid)
                            ticket["state"] = TicketState.ACTIVE
                            ticket.pop("channel_id", None)
                            ticket.pop("reconcile_token", None)
                            opened_conf[uid][channel_id] = ticket
                            modified = True

            if modified:
                log.info(
                    f"Reconciled tickets in {guild.name}: "
                    f"{len(tickets_to_remove)} removed, {len(tickets_to_promote)} promoted"
                )

    async def _import_settings(self) -> None:
        settings_path = Path(__file__).parent / "settings.json"
        if not settings_path.exists():
            return

        try:
            text = settings_path.read_text(encoding="utf-8")
            data = json.loads(text)
        except Exception as e:
            log.error("Failed to load settings.json", exc_info=e)
            return

        conf_data = data.get("117117", {}).get("GUILD", {})
        if not conf_data:
            log.debug("No guild data found in settings.json")
            return

        count = 0
        for guild_id, guild_data in conf_data.items():
            try:
                guild_group = self.config.guild_from_id(int(guild_id))
                current_data = await guild_group.all()
                current_data.update(guild_data)
                await guild_group.set(current_data)
                count += 1
            except Exception as e:
                log.error(f"Failed to import settings for guild {guild_id}", exc_info=e)

        if count:
            log.info(f"Imported settings for {count} guilds from settings.json")

    async def initialize(self, target_guild: discord.Guild | None = None) -> None:
        if target_guild:
            data = await self.config.guild(target_guild).all()
            return await self._init_guild(target_guild, data)

        t1 = perf_counter()
        conf = await self.config.all_guilds()
        for gid, data in conf.items():
            if not data:
                continue
            guild = self.bot.get_guild(gid)
            if not guild:
                continue
            try:
                await self._init_guild(guild, data)
            except Exception as e:
                log.error(f"Failed to initialize tickets for {guild.name}", exc_info=e)

        td = (perf_counter() - t1) * 1000
        log.info(f"Tickets initialized in {round(td, 1)}ms")

    async def _init_guild(self, guild: discord.Guild, data: dict) -> None:
        # Stop and clear guild views from cache
        views = self.view_cache.setdefault(guild.id, [])
        for view in views:
            view.stop()
        self.view_cache[guild.id].clear()

        # Deploy Panel
        category_id = data.get("category_id")
        channel_id = data.get("channel_id")
        message_id = data.get("message_id")

        if category_id and channel_id and message_id:
            category = guild.get_channel(category_id)
            channel_obj = guild.get_channel(channel_id)

            if category and isinstance(channel_obj, discord.TextChannel):
                try:
                    # Validate visibility/existence
                    await channel_obj.fetch_message(message_id)

                    panelview = PanelView(self.bot, guild, self.config, data)
                    await panelview.start()
                    self.view_cache[guild.id].append(panelview)
                except discord.NotFound:
                    log.warning(f"Message {message_id} not found in {channel_obj.name}, cannot deploy panel.")
                except discord.Forbidden:
                    log.error(f"Cannot see panel channel in {guild.name}")
                except Exception as e:
                    log.error(f"Failed to deploy panel in {guild.name}", exc_info=e)

        # Refresh view for logs of opened tickets
        for uid, opened_tickets in data["opened"].items():
            member = guild.get_member(int(uid))
            if not member:
                continue
            for ticket_channel_id, ticket_info in opened_tickets.items():
                ticket_channel = guild.get_channel_or_thread(int(ticket_channel_id))
                if not ticket_channel:
                    continue

                if message_id := ticket_info.get("message_id"):
                    if not isinstance(ticket_channel, (discord.TextChannel, discord.Thread)):
                        continue
                    view = CloseView(self.bot, self.config, int(uid), ticket_channel)
                    self.bot.add_view(view, message_id=message_id)
                    self.view_cache[guild.id].append(view)

                if not ticket_info["logmsg"]:
                    continue

    @tasks.loop(minutes=20)
    async def auto_close(self):
        all_guilds_conf = await self.config.all_guilds()
        for gid, guild_conf in all_guilds_conf.items():
            if not guild_conf:
                continue
            guild = self.bot.get_guild(gid)
            if not guild:
                continue
            inactive = guild_conf["inactive"]
            if not inactive:
                continue
            opened = guild_conf["opened"]
            if not opened:
                continue
            for uid, tickets in opened.items():
                member = guild.get_member(int(uid))
                if not member:
                    continue
                for channel_id, ticket in tickets.items():
                    has_response = ticket.get("has_response")
                    if has_response and channel_id not in self.valid:
                        self.valid.append(channel_id)
                        continue
                    if channel_id in self.valid:
                        continue
                    channel = guild.get_channel_or_thread(int(channel_id))
                    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
                        continue
                    now = datetime.datetime.now().astimezone()
                    opened_on = datetime.datetime.fromisoformat(ticket["opened"])
                    hastyped = await ticket_owner_hastyped(channel, member)
                    if hastyped and channel_id not in self.valid:
                        self.valid.append(channel_id)
                        continue
                    td = (now - opened_on).total_seconds() / 3600
                    next_td = td + 0.33
                    if td < inactive <= next_td:
                        warning = (
                            "If you do not respond to this ticket "
                            "within the next 20 minutes it will be closed automatically."
                        )
                        await channel.send(f"{member.mention}\n{warning}")
                        continue
                    elif td < inactive:
                        continue

                    time = "hours" if inactive != 1 else "hour"
                    try:
                        await close_ticket(
                            self.bot,
                            member,
                            guild,
                            channel,
                            guild_conf,
                            "(Auto-Close) Opened ticket with no response for " + f"{inactive} {time}",
                            self.bot.user.name if self.bot.user else "AutoClose",
                            self.config,
                        )
                        log.info(
                            f"Ticket opened by {member.name} has been auto-closed.\n"
                            f"Has typed: {hastyped}\n"
                            f"Hours elapsed: {td}"
                        )
                    except Exception as e:
                        log.error(f"Failed to auto-close ticket for {member} in {guild.name}\nException: {e}")

    @auto_close.before_loop
    async def before_auto_close(self):
        await self.bot.wait_until_red_ready()
        await asyncio.sleep(300)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if not member:
            return
        guild = member.guild
        if not guild:
            return
        conf = await self.config.guild(guild).all()
        opened = conf["opened"]
        if str(member.id) not in opened:
            return
        tickets = opened[str(member.id)]
        if not tickets:
            return

        for cid in tickets:
            chan = guild.get_channel_or_thread(int(cid))
            if not isinstance(chan, (discord.TextChannel, discord.Thread)):
                continue
            try:
                await close_ticket(
                    bot=self.bot,
                    member=member,
                    guild=guild,
                    channel=chan,
                    conf=conf,
                    reason="User left guild(Auto-Close)",
                    closedby=self.bot.user.name if self.bot.user else "AutoClose",
                    config=self.config,
                )
            except Exception as e:
                log.error(f"Failed to auto-close ticket for {member} leaving {member.guild}\nException: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        if not channel:
            return
        guild = channel.guild
        conf = await self.config.guild(guild).all()
        pruned = await prune_invalid_tickets(guild, conf, self.config)
        if pruned:
            log.info("Pruned old ticket channels")
