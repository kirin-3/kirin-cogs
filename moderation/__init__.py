"""Warnings, role-strip mutes, kicks, bans, and user info"""

from .moderation import Moderation


async def setup(bot):
    bot.remove_command("warnings")  # free the name so our cog can register; sync_warnings sorts out who keeps it
    cog = Moderation(bot)
    await bot.add_cog(cog)
    cog.sync_warnings()
