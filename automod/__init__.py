from .automod import AutoMod

__red_end_user_data_statement__ = (
    "This cog keeps a log of its last 250 actions: the time, the member's ID and name, the channel, the rules that "
    "matched and what was done. It stores no message text. Recent message counts for spam rules are kept in memory "
    "only. Red data-deletion requests remove the user's log entries and counts."
)


async def setup(bot):
    await bot.add_cog(AutoMod(bot))
