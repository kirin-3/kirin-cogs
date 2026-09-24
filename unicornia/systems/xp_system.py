"""
XP and Leveling system for Unicornia
"""

import asyncio
import contextlib
import logging
import os
import random
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

import discord

from ..database import DatabaseManager
from ..types import LevelStats
from .card_generator import XPCardGenerator

log = logging.getLogger("red.kirin_cogs.unicornia.xp")


class XPSystem:
    """Handles XP gain, leveling, and rewards"""

    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
        self._state_lock = asyncio.Lock()
        self._stopping = False
        self.xp_cooldowns: dict[int, float] = {}
        self.xp_buffer: dict[tuple[int, int], int] = {}
        # Config Cache
        self._config_cache = {"xp_enabled": True, "xp_cooldown": 60, "xp_per_message": 1}
        self._guild_config_cache = {}  # {guild_id: {'xp_included_channels': set(), 'excluded_roles': set()}}

        # Entries contain effective XP (including pending messages) and a cumulative threshold.
        self.user_xp_cache: OrderedDict[tuple[int, int], dict[str, int]] = OrderedDict()
        self.user_xp_cache_size = 5000

        self._voice_xp_task = None
        self._message_xp_task = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._background_tasks: set[asyncio.Task[Any]] = set()
        # (guild_id, user_id) -> (lock, tasks using it); level rewards for one member are applied in order
        self._reward_locks: dict[tuple[int, int], tuple[asyncio.Lock, int]] = {}

        # Initialize XP card generator
        # Pass the cog root directory (parent of 'systems')
        cog_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.card_generator = XPCardGenerator(cog_dir)

        # Start loops
        self.start_loops()

        # Initialize Config Cache
        self._create_task(self._init_config_cache())

    def _create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def _init_config_cache(self):
        """Initialize configuration cache"""
        enabled = await self.config.xp_enabled()
        cooldown = await self.config.xp_cooldown()
        per_message = await self.config.xp_per_message()
        self._config_cache["xp_enabled"] = enabled if isinstance(enabled, bool) else True
        self._config_cache["xp_cooldown"] = cooldown if type(cooldown) is int and cooldown >= 0 else 60
        self._config_cache["xp_per_message"] = per_message if type(per_message) is int and per_message >= 0 else 1

    @staticmethod
    def _configured_ids(value: object) -> set[int]:
        """Treat missing or malformed channel/role lists as empty."""
        if not isinstance(value, (list, tuple, set)):
            return set()
        return {item for item in value if type(item) is int and item > 0}

    def start_loops(self):
        """Start XP loops"""
        if self._stopping:
            return
        if not self._voice_xp_task:
            self._voice_xp_task = asyncio.create_task(self._voice_xp_loop())
        if not self._message_xp_task:
            self._message_xp_task = asyncio.create_task(self._message_xp_loop())

    async def stop_loops(self) -> None:
        """Drain accepted XP work before the owning cog closes the database."""
        self._stopping = True
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._drain_xp())
        # Cancelling a shutdown caller must not cancel the writes/callbacks being
        # drained, or return while committed XP still needs cache bookkeeping.
        await self._wait_for_completion(self._shutdown_task)

    async def _drain_xp(self) -> None:
        """Run once per instance; all shutdown callers wait for this same task."""
        loops = [task for task in (self._voice_xp_task, self._message_xp_task) if task is not None]
        for task in loops:
            task.cancel()
        await asyncio.gather(*loops, return_exceptions=True)
        self._voice_xp_task = None
        self._message_xp_task = None

        # Writes complete their bookkeeping on cancellation; callbacks may still
        # need the database for rewards. Neither can outlive database shutdown.
        while self._background_tasks:
            await asyncio.gather(*tuple(self._background_tasks), return_exceptions=True)
        await self._flush_buffer()
        if self.xp_buffer:
            log.error("XP shutdown could not persist %s pending entries", len(self.xp_buffer))

    async def _voice_xp_loop(self):
        """Background task to award XP to users in voice channels"""
        await self.bot.wait_until_ready()

        while True:
            try:
                # Wait for 1 minute
                await asyncio.sleep(60)

                # Check global enable (Cached)
                if not self._config_cache.get("xp_enabled", True):
                    continue

                xp_amount = 1  # Trickle amount per minute
                pending_updates = []

                for guild in self.bot.guilds:
                    # Get whitelist and exclusions (Config)
                    included_channels = self._configured_ids(await self.config.guild(guild).xp_included_channels())
                    double_xp_channels = self._configured_ids(await self.config.guild(guild).xp_double_channels())
                    excluded_roles = self._configured_ids(await self.config.guild(guild).excluded_roles())

                    for channel in guild.voice_channels:
                        # Skip if channel is not in whitelist
                        if channel.id not in included_channels:
                            continue

                        # Calculate XP amount for this channel
                        current_xp_amount = xp_amount
                        if channel.id in double_xp_channels:
                            current_xp_amount *= 2

                        # Process members
                        for member in channel.members:
                            if member.bot:
                                continue

                            # Skip self-deafened or afk (optional, but good for anti-abuse)
                            if member.voice.self_deaf or member.voice.deaf:
                                continue

                            # Skip excluded roles
                            if any(role.id in excluded_roles for role in member.roles):
                                continue

                            # Add to batch
                            pending_updates.append((member.id, guild.id, current_xp_amount))

                # Process bulk update
                if pending_updates:
                    await self._award_voice_xp(pending_updates)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in voice XP loop: {e}")
                await asyncio.sleep(60)  # Wait before retry

    async def _message_xp_loop(self):
        """Background task to flush message XP buffer and clean memory"""
        counter = 0
        while True:
            try:
                await asyncio.sleep(30)  # Flush every 30 seconds
                await self._flush_buffer()

                # Cleanup cooldowns every 10 minutes (20 iterations)
                counter += 1
                if counter >= 20:
                    async with self._state_lock:
                        self._cleanup_cooldowns()
                    counter = 0

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in message XP loop: {e}")
                await asyncio.sleep(30)

    def _cleanup_cooldowns(self):
        """Remove stale cooldown entries to prevent memory leaks"""
        current_time = time.time()
        # Default cooldown 60s, checking 120s ensures we don't delete active cooldowns
        # Using 3600 (1 hour) as a safe stale threshold
        stale_threshold = 3600

        to_remove = [
            user_id for user_id, timestamp in self.xp_cooldowns.items() if current_time - timestamp > stale_threshold
        ]

        for user_id in to_remove:
            del self.xp_cooldowns[user_id]

    async def _complete_write_locked(self, write: Coroutine[Any, Any, None], on_commit: Callable[[], None]) -> None:
        """Finish persistence and bookkeeping before cancellation releases the state lock.

        Caller holds _state_lock. Repeated cancellation of the caller must not
        detach the write or leave a committed gain pending for a second flush.
        """

        async def commit() -> None:
            await write
            on_commit()

        task = asyncio.create_task(commit())
        self._background_tasks.add(task)
        try:
            await self._wait_for_completion(task)
        finally:
            self._background_tasks.discard(task)

    @staticmethod
    async def _wait_for_completion(task: asyncio.Task[None]) -> None:
        """Defer caller cancellation until owned work has a definite outcome."""
        cancelled = False
        while True:
            try:
                await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancelled = True
            except Exception:
                if cancelled:
                    log.exception("XP operation failed while its caller was being cancelled")
                    raise asyncio.CancelledError from None
                raise
        if cancelled:
            raise asyncio.CancelledError

    async def _award_voice_xp(self, updates: list[tuple[int, int, int]]) -> None:
        """Persist a voice batch and invalidate only successfully awarded entries.

        Rewards for levels reached through voice are granted without an announcement.
        """
        updates = [(uid, gid, amount) for uid, gid, amount in updates if amount > 0]
        if not updates:
            return
        async with self._state_lock:
            if self._stopping:
                return

            gained: dict[tuple[int, int], int] = {}
            for uid, gid, amount in updates:
                gained[(uid, gid)] = gained.get((uid, gid), 0) + amount
            before = {key: await self._effective_xp_locked(*key) for key in gained}

            def invalidate() -> None:
                for uid, gid, _ in updates:
                    self.user_xp_cache.pop((uid, gid), None)

            await self._complete_write_locked(self.db.xp.add_xp_bulk(updates), invalidate)

            # Started before the lock is released, so shutdown waits for them before closing the database
            for (uid, gid), amount in gained.items():
                old_level = self.db.calculate_level_stats(before[(uid, gid)]).level
                new_level = self.db.calculate_level_stats(before[(uid, gid)] + amount).level
                if new_level > old_level:
                    self._start_level_up(uid, gid, None, old_level, new_level)

    async def _flush_buffer(self) -> None:
        """Commit pending messages once, retaining them if the transaction fails."""
        async with self._state_lock:
            if not self.xp_buffer:
                return
            updates = [(uid, gid, amount) for (uid, gid), amount in self.xp_buffer.items()]
            try:
                # Cache totals already include these gains. Only clear the buffer.
                await self._complete_write_locked(self.db.xp.add_xp_bulk(updates), self.xp_buffer.clear)
            except Exception:
                log.exception("Failed to flush XP buffer; retaining %s entries for retry", len(updates))

    def _get_user_cache_data(self, user_id: int, guild_id: int) -> dict[str, int] | None:
        """Get user data from cache, handling LRU. Caller holds _state_lock."""
        key = (user_id, guild_id)
        if key in self.user_xp_cache:
            self.user_xp_cache.move_to_end(key)
            return self.user_xp_cache[key]
        return None

    def _set_user_cache_data(self, user_id: int, guild_id: int, data: dict[str, int]) -> None:
        """Set user data in cache, handling LRU eviction. Caller holds _state_lock."""
        key = (user_id, guild_id)
        self.user_xp_cache[key] = data
        self.user_xp_cache.move_to_end(key)

        if len(self.user_xp_cache) > self.user_xp_cache_size:
            self.user_xp_cache.popitem(last=False)

    def _cache_stats_locked(self, user_id: int, guild_id: int, stats: LevelStats) -> dict[str, int]:
        data = {
            "xp": stats.total_xp,
            "level": stats.level,
            "next_level_total_xp": self.db.get_total_xp_req_for_level(stats.level + 1),
        }
        self._set_user_cache_data(user_id, guild_id, data)
        return data

    async def _read_stats_locked(self, user_id: int, guild_id: int) -> LevelStats:
        """Read committed plus pending XP. Caller holds _state_lock."""
        xp = await self.db.xp.get_user_xp(user_id, guild_id)
        return self.db.calculate_level_stats(xp + self.xp_buffer.get((user_id, guild_id), 0))

    async def _effective_xp_locked(self, user_id: int, guild_id: int) -> int:
        """Committed plus pending XP, from the cache when present. Caller holds _state_lock."""
        cached = self._get_user_cache_data(user_id, guild_id)
        if cached is not None:
            return cached["xp"]
        return (await self._read_stats_locked(user_id, guild_id)).total_xp

    async def process_message(self, message: discord.Message):
        """Process a message for XP gain (Optimized).

        Called from on_message_without_command, so commands are already filtered out.
        """
        if self._stopping or message.author.bot or not message.guild:
            return

        # Check cached config
        if not self._config_cache.get("xp_enabled", True):
            return

        # Check cooldown
        user_id = message.author.id
        current_time = time.time()
        cooldown = self._config_cache.get("xp_cooldown", 60)

        if user_id in self.xp_cooldowns and current_time - self.xp_cooldowns[user_id] < cooldown:
            return

        guild_id = message.guild.id

        # --- EXCLUSION CHECKS ---

        # 1. Channel Whitelist Check
        included_channels = self._configured_ids(await self.config.guild(message.guild).xp_included_channels())

        # Check channel ID directly
        channel_id = message.channel.id
        is_included = channel_id in included_channels

        # If not included, check if it's a thread and if parent is included
        if (
            not is_included
            and isinstance(message.channel, discord.Thread)
            and message.channel.parent_id in included_channels
        ):
            is_included = True

        if not is_included:
            return

        # 2. Role Exclusion Check
        excluded_roles = self._configured_ids(await self.config.guild(message.guild).excluded_roles())
        if isinstance(message.author, discord.Member) and any(
            role.id in excluded_roles for role in message.author.roles
        ):
            return

        # --- XP CALCULATION (LRU Cache) ---

        xp_amount = self._config_cache.get("xp_per_message", 1)
        if xp_amount <= 0:
            return

        # Check for Double XP Channel
        double_xp_channels = self._configured_ids(await self.config.guild(message.guild).xp_double_channels())

        # Check channel ID directly
        is_double = channel_id in double_xp_channels

        # If not included, check if it's a thread and if parent is included
        if (
            not is_double
            and isinstance(message.channel, discord.Thread)
            and message.channel.parent_id in double_xp_channels
        ):
            is_double = True

        if is_double:
            xp_amount *= 2

        transition: tuple[int, int] | None = None
        async with self._state_lock:
            if self._stopping:
                return
            # Config/context awaits above allow another message to win admission.
            current_time = time.time()
            if user_id in self.xp_cooldowns and current_time - self.xp_cooldowns[user_id] < cooldown:
                return

            cache_data = self._get_user_cache_data(user_id, guild_id)
            if cache_data is None:
                stats = await self._read_stats_locked(user_id, guild_id)
                # Shutdown can begin while the initial database read is pending.
                if self._stopping:
                    return
                cache_data = self._cache_stats_locked(user_id, guild_id, stats)

            new_total_xp = cache_data["xp"] + xp_amount
            if new_total_xp >= cache_data["next_level_total_xp"]:
                new_stats = self.db.calculate_level_stats(new_total_xp)
                if new_stats.level > cache_data["level"]:
                    transition = (cache_data["level"], new_stats.level)
                self._cache_stats_locked(user_id, guild_id, new_stats)
            else:
                cache_data["xp"] = new_total_xp

            key = (user_id, guild_id)
            self.xp_buffer[key] = self.xp_buffer.get(key, 0) + xp_amount
            self.xp_cooldowns[user_id] = time.time()

        if transition is not None:
            try:
                await self._create_task(self._handle_level_up(message, *transition))
            except Exception:
                log.exception("Level-up side effects failed for user %s in guild %s", user_id, guild_id)

    async def _handle_level_up(self, message, old_level: int, new_level: int):
        """Handle level up rewards and notifications"""
        await self._level_up(message.author, message.guild, message.channel, old_level, new_level)

    def _start_level_up(
        self,
        user_id: int,
        guild_id: int,
        channel: discord.abc.Messageable | None,
        old_level: int,
        new_level: int,
    ) -> asyncio.Task[None] | None:
        """Start granting the rewards of a level-up from a direct award (admin or voice)."""
        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(user_id) if guild is not None else None
        if guild is None or member is None:
            log.warning(
                "User %s reached level %s in guild %s but isn't cached; level rewards %s-%s were not granted",
                user_id,
                new_level,
                guild_id,
                old_level + 1,
                new_level,
            )
            return None
        return self._create_task(self._safe_level_up(member, guild, channel, old_level, new_level))

    async def _safe_level_up(
        self,
        member: discord.Member,
        guild: discord.Guild,
        channel: discord.abc.Messageable | None,
        old_level: int,
        new_level: int,
    ) -> None:
        try:
            await self._level_up(member, guild, channel, old_level, new_level)
        except Exception:
            log.exception("Level-up side effects failed for user %s in guild %s", member.id, guild.id)

    async def _level_up(
        self,
        member: discord.Member,
        guild: discord.Guild,
        channel: discord.abc.Messageable | None,
        old_level: int,
        new_level: int,
    ) -> None:
        """Grant the rewards of every level passed, then announce the new level in channel (if any)."""
        # Tasks for one member reach this in the order their level-ups happened, and take turns here,
        # so a later level's role removal can't run before an earlier level's role is added
        async with self._member_reward_lock(guild.id, member.id):
            footer_texts = await self._grant_level_rewards(member, guild, old_level, new_level)
        if channel is None:
            return

        # Random Color for Embed
        embed_color = discord.Color(random.randint(0, 0xFFFFFF))
        embed = discord.Embed(
            description=f"Congratulations {member.mention}, you have reached level **{new_level}**!", color=embed_color
        )
        if footer_texts:
            embed.set_footer(text=" • ".join(footer_texts))

        await channel.send(embed=embed)

    @contextlib.asynccontextmanager
    async def _member_reward_lock(self, guild_id: int, user_id: int) -> AsyncIterator[None]:
        key = (guild_id, user_id)
        lock, users = self._reward_locks.get(key, (asyncio.Lock(), 0))
        self._reward_locks[key] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._reward_locks[key]
            if users == 1:
                del self._reward_locks[key]
            else:
                self._reward_locks[key] = (lock, users - 1)

    async def _grant_level_rewards(
        self, member: discord.Member, guild: discord.Guild, old_level: int, new_level: int
    ) -> list[str]:
        """Apply the role and currency rewards of every level above old_level up to new_level.

        One level-up can pass several levels (an admin award, voice XP), and each level's rewards count.

        Returns:
            A summary line for each change.
        """
        summary: list[str] = []

        # Rewards come ordered by level, so for a role set at several levels (given at 5, removed at 10)
        # the highest level passed decides
        role_changes: dict[int, tuple[int, bool]] = {}
        for level, role_id, remove in await self.db.xp.get_all_xp_role_rewards(guild.id):
            if old_level < level <= new_level:
                role_changes[role_id] = (level, bool(remove))

        if role_changes:
            # The cached member only learns about role changes when Discord sends the update, which can
            # be after an earlier level-up's change, so read the roles the member holds right now
            with contextlib.suppress(discord.HTTPException):
                member = await guild.fetch_member(member.id)
        held = {role.id for role in member.roles}
        for role_id, (level, remove) in role_changes.items():
            role = guild.get_role(role_id)
            if not role:
                continue
            try:
                if remove and role_id in held:
                    await member.remove_roles(role, reason=f"XP level {level} role removal")
                    summary.append(f"Removed role: {role.name}")
                elif not remove and role_id not in held:
                    await member.add_roles(role, reason=f"XP level {level} role reward")
                    summary.append(f"Gained role: {role.name}")
            except discord.HTTPException as e:
                log.warning("Could not update level %s role %s for user %s: %s", level, role_id, member.id, e)

        currency_gained = 0
        for level, amount in await self.db.xp.get_xp_currency_rewards(guild.id):
            if old_level < level <= new_level and amount > 0:
                await self.db.economy.add_currency(
                    member.id, amount, "level_reward", f"level_{level}", note=f"Level {level} reward"
                )
                currency_gained += amount

        if currency_gained > 0:
            currency_name = await self.config.currency_name()
            summary.append(f"Gained {currency_gained} {currency_name}")

        return summary

    async def get_user_level_stats(self, user_id: int, guild_id: int) -> LevelStats:
        """Get user's level statistics.

        Args:
            user_id: User ID.
            guild_id: Guild ID.

        Returns:
            LevelStats object.
        """
        async with self._state_lock:
            stats = await self._read_stats_locked(user_id, guild_id)
            self._cache_stats_locked(user_id, guild_id, stats)
            return stats

    async def get_leaderboard(self, guild_id: int, limit: int = 10, offset: int = 0) -> list[tuple]:
        """Get XP leaderboard for a guild.

        Args:
            guild_id: Guild ID.
            limit: Limit results.
            offset: Offset results.

        Returns:
            List of (UserId, Xp) tuples.
        """
        return await self.db.xp.get_top_xp_users(guild_id, limit, offset)

    async def get_filtered_leaderboard(self, guild: discord.Guild) -> list[tuple]:
        """Get filtered XP leaderboard for a guild (only current members).

        Args:
            guild: Discord guild.

        Returns:
            List of (UserId, Xp) tuples.
        """
        all_users = await self.db.xp.get_all_guild_xp(guild.id)

        filtered_users = []
        for user_id, xp in all_users:
            member = guild.get_member(user_id)
            if member and not member.bot:
                filtered_users.append((user_id, xp))

        # Limit to 30 pages (300 users)
        return filtered_users[:300]

    def get_progress_bar(self, current_xp: int, required_xp: int, length: int = 10) -> str:
        """Generate a progress bar for XP.

        Args:
            current_xp: Current XP amount.
            required_xp: Required XP for next level.
            length: Length of the bar in characters.

        Returns:
            Progress bar string.
        """
        if required_xp == 0:
            return "█" * length

        filled_length = int(length * current_xp / required_xp)
        bar = "█" * filled_length + "░" * (length - filled_length)
        return bar

    async def award_xp(
        self,
        user_id: int,
        guild_id: int,
        amount: int,
        note: str = "",
        channel: discord.abc.Messageable | None = None,
    ) -> bool:
        """Award XP to a user (admin only).

        The rewards of every level the award passes are granted, and the new level is announced in
        channel when one is given.

        Args:
            user_id: User ID.
            guild_id: Guild ID.
            amount: Amount of XP to award.
            note: Optional note for the award.
            channel: Where to announce a level-up.

        Returns:
            Success boolean.
        """
        if amount <= 0:
            return False

        level_up = None
        try:
            async with self._state_lock:
                if self._stopping:
                    return False
                xp_before = await self._effective_xp_locked(user_id, guild_id)

                def invalidate() -> None:
                    self.user_xp_cache.pop((user_id, guild_id), None)

                await self._complete_write_locked(
                    self.db.xp.add_xp(user_id, guild_id, amount),
                    invalidate,
                )

                old_level = self.db.calculate_level_stats(xp_before).level
                new_level = self.db.calculate_level_stats(xp_before + amount).level
                if new_level > old_level:
                    # Started before the lock is released, so shutdown waits for it before closing the database
                    level_up = self._start_level_up(user_id, guild_id, channel, old_level, new_level)
        except Exception:
            return False

        if level_up is not None:
            await level_up
        return True
