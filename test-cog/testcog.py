from redbot.core import commands


class TestCog(commands.Cog):
    """Test cog to verify structure"""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def test(self, ctx):
        """Test command"""
        await ctx.send("Test cog is working!")
