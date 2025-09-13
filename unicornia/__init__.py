# Unicornia - Full-Featured Leveling and Economy Cog
# A complete Red bot cog that provides comprehensive leveling and economy features

from .unicornia import Unicornia

__red_end_user_data_statement__ = "This cog stores user level, XP, currency, and economy data in its own SQLite database."


async def setup(bot):
    cog = Unicornia(bot)
    await bot.add_cog(cog)
