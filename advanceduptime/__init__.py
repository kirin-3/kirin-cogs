from .advanceduptime import AdvancedUptime


async def setup(bot):
    await bot.add_cog(AdvancedUptime(bot))
