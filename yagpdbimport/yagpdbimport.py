from redbot.core import commands


class YagpdbImport(commands.Cog):
    """Import warnings from YAGPDB."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def yagsay(self, ctx: commands.Context, *, text: str) -> None:
        """Make the bot send text, to test whether YAGPDB responds to it. Example: `[p]yagsay -dumpwarns 1234`"""
        await ctx.send(text)
