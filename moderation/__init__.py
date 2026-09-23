"""Warnings, role-strip mutes, kicks, bans, and user info"""

from .moderation import Moderation


async def setup(bot):
    # Take over Red's plain-text [p]warnings; Moderation.cog_unload gives it back.
    await bot.add_cog(Moderation(bot, bot.remove_command("warnings")))
