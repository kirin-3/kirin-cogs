from .disboardreminder import DisboardReminder


async def setup(bot):
    await bot.add_cog(DisboardReminder(bot))
