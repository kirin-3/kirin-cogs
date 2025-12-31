import logging
import discord
from redbot.core import commands, Config
from redbot.core.bot import Red

log = logging.getLogger("red.kirin_cogs.nitroaward")

# Amount of currency to award when a user boosts the server
AWARD_AMOUNT = 5000

class NitroAward(commands.Cog):
    """
    Awards currency to users when they boost the server.
    """

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(
            self, identifier=84732819203, force_registration=True
        )
        default_user = {
            "last_boost_timestamp": None,
        }
        self.config.register_user(**default_user)
        # In-memory set to prevent concurrent processing of the same user
        self.processing_users = set()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        # Check if the user just started boosting
        # before.premium_since is None AND after.premium_since is NOT None
        if before.premium_since is None and after.premium_since is not None:
            # Prevent concurrent processing
            if after.id in self.processing_users:
                return
            
            self.processing_users.add(after.id)
            try:
                await self.process_boost_reward(after)
            finally:
                self.processing_users.discard(after.id)

    async def process_boost_reward(self, member: discord.Member) -> None:
        # Robustness check: Ensure premium_since is still present
        if member.premium_since is None:
            return

        boost_timestamp = member.premium_since.timestamp()
        last_awarded = await self.config.user(member).last_boost_timestamp()

        # Check if we already awarded for this specific boost instance
        if last_awarded == boost_timestamp:
            return

        unicornia = self.bot.get_cog("Unicornia")
        if not unicornia:
            log.warning("Unicornia cog is not loaded. Cannot award currency to %s (%s).", member.display_name, member.id)
            return

        try:
            success = await unicornia.add_balance(
                user_id=member.id,
                amount=AWARD_AMOUNT,
                reason="Nitro Boost Reward",
                source="NitroAward"
            )
            if success:
                log.info("Awarded %s currency to %s (%s) for boosting.", AWARD_AMOUNT, member.display_name, member.id)
                # Mark as awarded
                await self.config.user(member).last_boost_timestamp.set(boost_timestamp)
            else:
                log.error("Failed to award currency to %s (%s). Unicornia system might not be ready.", member.display_name, member.id)
        except Exception as e:
            log.exception("Error awarding currency to %s (%s): %s", member.display_name, member.id, e)
