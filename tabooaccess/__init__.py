from .tabooaccess import TabooAccess

async def setup(bot):
    await bot.add_cog(tabooaccess())

__red_end_user_data_statement__ = "This cog does not store any end user data."