from .unicorn_ai import UnicornAI

async def setup(bot):
    await bot.add_cog(UnicornAI(bot))
