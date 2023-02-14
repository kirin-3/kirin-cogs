from .void import Void, __red_end_user_data_statement__

def setup(bot):
    cog = Void(bot)
    bot.add_cog(cog)