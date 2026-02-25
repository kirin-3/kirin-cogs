"""AntiNuke cog for Red-DiscordBot."""

from .antinuke import AntiNuke

__red_end_user_data_statement__ = (
    "This cog stores user IDs for trusted users and quarantined users. "
    "Quarantined user data includes their previous role IDs for restoration purposes. "
    "This data is stored per-guild and can be cleared by server administrators."
)


async def setup(bot):
    """Load the AntiNuke cog."""
    await bot.add_cog(AntiNuke(bot))
