from .unicorndocs import UnicornDocs

__red_end_user_data_statement__ = "This cog stores vector embeddings of documentation content for AI-powered question answering. No personal user data is stored."


def setup(bot):
    bot.add_cog(UnicornDocs(bot))
