from .confess import Confess


async def setup(bot):
    await bot.add_cog(Confess(bot))
