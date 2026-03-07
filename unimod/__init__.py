"""UniMod - AI-Powered Auto Moderation Cog"""

__version__ = "1.0.0"
__author__ = "Kirin"
__license__ = "MIT"

from .unimod import UniMod


async def setup(bot):
    await bot.add_cog(UniMod(bot))
