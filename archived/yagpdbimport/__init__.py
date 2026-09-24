"""YAGPDB warnings import cog"""

from .yagpdbimport import YagpdbImport


async def setup(bot):
    await bot.add_cog(YagpdbImport(bot))
