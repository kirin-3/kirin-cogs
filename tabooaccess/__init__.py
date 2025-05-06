from .tabooaccess import tabooaccess

async def setup(bot):
    await bot.add_cog(tabooaccess())