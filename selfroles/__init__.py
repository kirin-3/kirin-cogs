from .selfroles import SelfRoles

__red_end_user_data_statement__ = "This cog stores no user data."


async def setup(bot):
    await bot.add_cog(SelfRoles(bot))
