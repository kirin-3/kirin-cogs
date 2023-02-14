import discord
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.config import Config
import asyncio

class DeleteMessagesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.task = bot.loop.create_task(self.delete_messages_task())

    async def delete_messages_task(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            target_channel = self.bot.get_channel(1074908239734505583) 
            ignored_user = self.bot.get_user(474075064069783552) 
            async for message in target_channel.history(limit=None):
                if message.author == self.bot.user or message.author == ignored_user:
                    continue
                await message.delete()
                await message.channel.send("Purged void.")
            await asyncio.sleep(24 * 60 * 60) 

    @commands.command()
    async def start_delete(self, ctx):
        await ctx.send("Deleting messages in channel every 24 hours.")

def setup(bot):
    bot.add_cog(DeleteMessagesCog(bot))
