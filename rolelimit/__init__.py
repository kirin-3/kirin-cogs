from .rolelimit import RoleLimit


async def setup(bot):
    await bot.add_cog(RoleLimit(bot))
