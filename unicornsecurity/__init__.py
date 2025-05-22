"""Unicorn Security Cog for cleaning non-tenor image links"""

__version__ = "1.0.0"
__author__ = "Unicornia Team"
__credits__ = ["Kirin"]
__license__ = "MIT"


from .imagefilter import ImageFilter


async def setup(bot):
    await bot.add_cog(ImageFilter(bot)) 