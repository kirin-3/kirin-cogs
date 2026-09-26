from .mjolnir import Mjolnir


async def setup(bot):
    await bot.add_cog(Mjolnir(bot))
