from .conversationgames import ConversationGames


async def setup(bot):
    await bot.add_cog(ConversationGames(bot))
