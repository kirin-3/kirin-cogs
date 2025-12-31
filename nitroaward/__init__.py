from .nitroaward import NitroAward

async def setup(bot):
    await bot.add_cog(NitroAward(bot))
