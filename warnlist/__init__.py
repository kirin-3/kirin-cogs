"""Dated, paginated warnings list"""

from .warnlist import WarnList


async def setup(bot):
    # Take over Red's plain-text [p]warnings; WarnList.cog_unload gives it back.
    await bot.add_cog(WarnList(bot, bot.remove_command("warnings")))
