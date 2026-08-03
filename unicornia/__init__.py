# Unicornia - Full-Featured Leveling and Economy Cog
# A complete Red bot cog that provides comprehensive leveling and economy features

from .unicornia import Unicornia

__red_end_user_data_statement__ = (
    "This cog stores user level, XP, currency, inventory, game, relationship, and financial history data "
    "in SQLite. Deletion removes operational state and anonymizes retained accounting records."
)


async def setup(bot):
    cog = Unicornia(bot)
    await bot.add_cog(cog)
