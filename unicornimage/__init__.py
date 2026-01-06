from .unicornimage import UnicornImage

async def setup(bot):
    await bot.add_cog(UnicornImage(bot))
