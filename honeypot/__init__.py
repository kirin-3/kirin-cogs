from .honeypot import Honeypot

__red_end_user_data_statement__ = (
    "This cog stores guild-scoped Discord user IDs, prior role IDs, and quarantine timestamps so staff can "
    "restore quarantined members. Red data-deletion requests remove the user's quarantine records from every guild."
)


async def setup(bot):
    await bot.add_cog(Honeypot(bot))
