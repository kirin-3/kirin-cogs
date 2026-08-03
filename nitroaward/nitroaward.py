import logging

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .migrations import migrate_global_schema

log = logging.getLogger("red.kirin_cogs.nitroaward")

# Amount of currency to award when a user boosts the server
AWARD_AMOUNT = 5000


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
        self.config.register_global(schema_version=0, legacy_boost_records={})
        default_member = {
            "last_boost_timestamp": None,
        }
        self.config.register_member(**default_member)
        # In-memory set to prevent concurrent processing of the same
        # guild/member pair: {(guild_id, member_id)}
        self.processing_members: set[tuple[int, int]] = set()

    async def cog_load(self) -> None:
        await migrate_global_schema(self.config)

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

    async def process_boost_reward(self, member: discord.Member) -> None:
        # Robustness check: Ensure premium_since is still present
        if member.premium_since is None:
            return

        boost_timestamp = member.premium_since.timestamp()

        # Check if we already awarded for this specific boost instance
        if await self._already_awarded(member, boost_timestamp):
            return

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
            else:
                log.error(
                    "Failed to award currency to %s (%s): unexpected operation state %s.",
                    member.display_name,
                    member.id,
                    outcome.state,
                )
        except Exception as e:
            log.exception("Error awarding currency to %s (%s): %s", member.display_name, member.id, e)
