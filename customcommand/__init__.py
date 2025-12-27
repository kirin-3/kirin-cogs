"""Custom Command Cog"""

__version__ = "1.0.0"
__author__ = "Unicornia Team"
__credits__ = ["Kirin"]
__license__ = "MIT"


from .customcommand import CustomCommand


# Your bot's code continues here...
async def setup(bot):
    await bot.add_cog(CustomCommand(bot))