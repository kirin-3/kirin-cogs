from .rulesaccept import RulesAccept


async def setup(bot):
    await bot.add_cog(RulesAccept(bot))
