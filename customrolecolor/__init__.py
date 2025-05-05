"""Custom Role Color Cog"""

__version__ = "1.0.0"
__author__ = "Unicornia Team"
__credits__ = ["Kirin"]
__license__ = "MIT"


from .customrolecolor import CustomRoleColor


# Your bot's code continues here...
async def setup(bot):
    await bot.add_cog(CustomRoleColor())