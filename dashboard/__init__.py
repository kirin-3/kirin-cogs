from .dashboard import Dashboard

__red_end_user_data_statement__ = (
    "This cog does not persistently store data about users. Staff logins read the Discord account's ID and 2FA status "
    "once; the resulting session is held in memory only and ends after 12 hours, on logout, or when the cog unloads."
)


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
