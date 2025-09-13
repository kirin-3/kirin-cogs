"""Test Cog"""

__version__ = "1.0.0"
__author__ = "Unicornia Team"
__credits__ = ["Kirin"]
__license__ = "MIT"


from .testcog import TestCog


async def setup(bot):
    await bot.add_cog(TestCog(bot))
