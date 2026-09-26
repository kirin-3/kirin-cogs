from .selftimeout import SelfTimeout


async def setup(bot):
    await bot.add_cog(SelfTimeout(bot))
