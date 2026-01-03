"""Custom Emoji Cog"""
from .customemoji import CustomEmoji

async def setup(bot):
    await bot.add_cog(CustomEmoji(bot))
