"""Unicorn Documentation Q&A System Cog"""

__version__ = "1.0.0"
__author__ = "Unicornia Team"
__credits__ = ["Kirin"]
__license__ = "MIT"


from .unicorndocs_simple import UnicornDocsSimple as UnicornDocs


async def setup(bot):
    await bot.add_cog(UnicornDocs(bot))
