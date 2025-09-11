"""Verify User Cog"""

__version__ = "1.0.0"
__author__ = "Unicornia Team"
__credits__ = ["Kirin"]
__license__ = "MIT"


from .verifyuser import VerifyUser


async def setup(bot):
    await bot.add_cog(VerifyUser(bot))
