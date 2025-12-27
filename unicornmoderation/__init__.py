from .unicorn_moderation import UnicornModeration

async def setup(bot):
    await bot.add_cog(UnicornModeration(bot))