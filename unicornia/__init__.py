# Unicornia - Nadeko Migration Cog
# A Red bot cog that reads from Nadeko's SQLite database to provide leveling and economy features

from .unicornia import Unicornia

__red_end_user_data_statement__ = "This cog reads from an existing Nadeko SQLite database and does not store additional user data."


def setup(bot):
    cog = Unicornia(bot)
    bot.add_cog(cog)
