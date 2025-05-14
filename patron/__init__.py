"""Patreon API Integration Cog"""

__version__ = "1.0.0"
__author__ = "Kirin"
__license__ = "MIT"

from .patron import Patron, __red_end_user_data_statement__

async def setup(bot):
    await bot.add_cog(Patron(bot)) 