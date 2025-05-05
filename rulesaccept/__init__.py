from .rulesaccept import rulesaccept

async def setup(bot):
    await bot.add_cog(rulesaccept())