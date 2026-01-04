from .dailyreddit import DailyReddit

async def setup(bot):
    await bot.add_cog(DailyReddit(bot))
