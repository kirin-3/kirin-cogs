from .banlog import BanLog

__red_end_user_data_statement__ = (
    "This cog stores a copy of every non-bot message posted in Unicornia (content, latest edit, attachment filenames, "
    "and deletion time) for 7 days. When a member is banned, their messages from that week are copied into a "
    "permanent ban record with the moderator and reason. Red data-deletion requests remove the user's stored "
    "messages; stricter requests also remove their ban records and replace them as moderator with a placeholder."
)


async def setup(bot):
    await bot.add_cog(BanLog(bot))
