import logging
import time

import discord
from discord.ext import tasks
from redbot.core import Config, commands
from redbot.core.bot import Red

from .migrations import migrate_global_schema

log = logging.getLogger("red.kirin_cogs.nitroaward")

# Amount of currency to award when a user boosts the server
AWARD_AMOUNT = 5000
RETRY_MINUTES = 15


class NitroAward(commands.Cog):
    """
    Awards currency to users when they boost the server.
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=84732819203, force_registration=True)
        # Marker for migrations.py; 0 = legacy unmigrated record
        # legacy_boost_records: {user_id_str: boost_timestamp} moved out of the
        # legacy global user scope; only consulted for exact-event matches.
        # catch_up_since: boosts that started after this POSIX time are rewarded even if their
        # member update was missed (bot offline or restarting). Set once, never moved.
        self.config.register_global(schema_version=0, legacy_boost_records={}, catch_up_since=None)
        default_member = {
            "last_boost_timestamp": None,
            # A seen boost whose reward hasn't settled yet; retried until it does.
            "pending_boost_timestamp": None,
        }
        self.config.register_member(**default_member)
        # In-memory set to prevent concurrent processing of the same
        # guild/member pair: {(guild_id, member_id)}
        self.processing_members: set[tuple[int, int]] = set()

    async def cog_load(self) -> None:
        await migrate_global_schema(self.config)
        if not isinstance(await self.config.catch_up_since(), int | float):
            await self.config.catch_up_since.set(await self._latest_recorded_boost() or time.time())
        self.retry_pending.start()

    async def _latest_recorded_boost(self) -> float | None:
        """The newest boost this cog has seen. Any later, unrewarded boost was missed."""
        seen = [
            ts
            for members in (await self.config.all_members()).values()
            if isinstance(members, dict)
            for data in members.values()
            if isinstance(data, dict)
            for ts in (data.get("last_boost_timestamp"), data.get("pending_boost_timestamp"))
            if isinstance(ts, int | float)
        ]
        legacy = await self.config.legacy_boost_records()
        if isinstance(legacy, dict):
            seen += [ts for ts in legacy.values() if isinstance(ts, int | float)]
        return max(seen, default=None)

    async def _catch_up_boosts(self) -> None:
        """Reward current boosters whose boost started after catch_up_since and was never rewarded."""
        since = await self.config.catch_up_since()
        if not isinstance(since, int | float):
            return
        for guild in self.bot.guilds:
            if guild.unavailable:
                continue
            for member in guild.premium_subscribers:
                if member.premium_since is None or member.premium_since.timestamp() <= since:
                    continue
                key = (guild.id, member.id)
                if key in self.processing_members:
                    continue
                self.processing_members.add(key)
                try:
                    # Already-rewarded boosts return early inside process_boost_reward.
                    await self.process_boost_reward(member)
                finally:
                    self.processing_members.discard(key)

    async def cog_unload(self) -> None:
        self.retry_pending.cancel()

    @tasks.loop(minutes=RETRY_MINUTES)
    async def retry_pending(self) -> None:
        """Retry boosts whose reward failed (Unicornia unloaded, not ready, or erroring), then
        reward boosts missed while offline. The first run is right after startup."""
        for guild_id, members in (await self.config.all_members()).items():
            guild = self.bot.get_guild(guild_id)
            if guild is None or guild.unavailable or not isinstance(members, dict):
                continue
            for member_id, data in members.items():
                pending = data.get("pending_boost_timestamp") if isinstance(data, dict) else None
                if not isinstance(pending, int | float):
                    continue
                member = guild.get_member(int(member_id))
                if member is None:  # left the server; nothing to credit in it
                    await self.config.member_from_ids(guild_id, int(member_id)).pending_boost_timestamp.clear()
                    continue
                key = (guild_id, member.id)
                if key in self.processing_members:
                    continue
                self.processing_members.add(key)
                try:
                    await self.process_boost_reward(member, float(pending))
                finally:
                    self.processing_members.discard(key)
        await self._catch_up_boosts()

    @retry_pending.before_loop
    async def _before_retry_pending(self) -> None:
        await self.bot.wait_until_red_ready()

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Delete guild-scoped boost timestamps and any legacy record."""
        for guild_id, members in (await self.config.all_members()).items():
            if isinstance(members, dict) and (user_id in members or str(user_id) in members):
                await self.config.member_from_ids(guild_id, user_id).clear()
        legacy = await self.config.legacy_boost_records()
        if isinstance(legacy, dict):
            removed = legacy.pop(str(user_id), None)
            removed = legacy.pop(user_id, removed)
            if removed is not None:
                await self.config.legacy_boost_records.set(legacy)
        # The migration deliberately retains the original user-scope value for
        # rollback. A deletion request must clear that source as well.
        await self.config.user_from_id(user_id).clear()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        # Check if the user just started boosting
        # before.premium_since is None AND after.premium_since is NOT None
        if before.premium_since is None and after.premium_since is not None:
            key = (after.guild.id, after.id)
            # Prevent concurrent processing of the same guild/member pair only;
            # the same user boosting another guild stays processable.
            if key in self.processing_members:
                return

            self.processing_members.add(key)
            try:
                await self.process_boost_reward(after)
            finally:
                self.processing_members.discard(key)

    async def _already_awarded(self, member: discord.Member, boost_timestamp: float) -> bool:
        """Check guild/member scope, then the legacy record (exact match only)."""
        member_ts = await self.config.member(member).last_boost_timestamp()
        if member_ts == boost_timestamp:
            return True

        legacy = await self.config.legacy_boost_records()
        if isinstance(legacy, dict) and legacy.get(str(member.id)) == boost_timestamp:
            # Exact-event match from the legacy global user scope. Adopt it into
            # guild/member scope so the legacy record is consulted at most once.
            await self.config.member(member).last_boost_timestamp.set(boost_timestamp)
            return True
        return False

    async def _settle_pending(self, member: discord.Member, boost_timestamp: float) -> None:
        group = self.config.member(member)
        if await group.pending_boost_timestamp() == boost_timestamp:
            await group.pending_boost_timestamp.clear()

    async def process_boost_reward(self, member: discord.Member, boost_timestamp: float | None = None) -> None:
        """Reward a boost: the member's current one, or a recorded `boost_timestamp` being retried."""
        if boost_timestamp is None:
            # Robustness check: Ensure premium_since is still present
            if member.premium_since is None:
                return
            boost_timestamp = member.premium_since.timestamp()

        # Check if we already awarded for this specific boost instance
        if await self._already_awarded(member, boost_timestamp):
            await self._settle_pending(member, boost_timestamp)
            return

        # Record the boost before trying, so any failure below is retried by retry_pending.
        await self.config.member(member).pending_boost_timestamp.set(boost_timestamp)

        unicornia = self.bot.get_cog("Unicornia")
        if not unicornia:
            log.warning(
                "Unicornia cog is not loaded. Cannot award currency to %s (%s).", member.display_name, member.id
            )
            return

        # Credit exclusively through the idempotent operation API: the key is
        # stable for this guild/member/boost event, so retries after a crash
        # return the prior settlement instead of crediting twice.
        operation_key = f"nitro:{member.guild.id}:{member.id}:{boost_timestamp}"

        try:
            outcome = await unicornia.apply_operation(  # type: ignore
                key=operation_key,
                user_id=member.id,
                amount=AWARD_AMOUNT,
                direction="credit",
                source="nitroaward",
                guild_id=member.guild.id,
                reason="Nitro Boost Reward",
            )
            if outcome is None:
                log.error(
                    "Failed to award currency to %s (%s). Unicornia system might not be ready.",
                    member.display_name,
                    member.id,
                )
                return

            if outcome.state in ("settled", "duplicate"):
                if outcome.state == "settled":
                    log.info(
                        "Awarded %s currency to %s (%s) for boosting.",
                        AWARD_AMOUNT,
                        member.display_name,
                        member.id,
                    )
                # The operation is durably settled (now or previously); local
                # completion is safe to record.
                await self.config.member(member).last_boost_timestamp.set(boost_timestamp)
                await self._settle_pending(member, boost_timestamp)
            else:
                log.error(
                    "Failed to award currency to %s (%s): unexpected operation state %s.",
                    member.display_name,
                    member.id,
                    outcome.state,
                )
        except Exception as e:
            log.exception("Error awarding currency to %s (%s): %s", member.display_name, member.id, e)
