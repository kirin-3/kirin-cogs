"""Try to lift Thor's hammer.

Ported from Kreusada's ``mjolnir`` (MIT; originally by Jojo, https://github.com/Just-Jojo/JojoCogs),
which was removed from Kreusada-Cogs in 2022. It keeps the original Config identifier
and cog name, so everyone's lift counts carry over.

The leaderboard now uses the bot's user cache instead of fetching every user from the
API, and pages with Red's SimpleMenu instead of the vendored reaction menus.
"""

import random

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify
from redbot.core.utils.views import SimpleMenu

SAYINGS = (
    "The hammer is strong, but so are you. Keep at it!",
    "Mjolnir budges a bit, but remains steadfast, as should you",
    "You've got this! I believe in you!",
    "Don't think it even moved... why don't you try again?",
)


def leaderboard_lines(all_users: dict, name_of) -> list[str]:
    """Ranked ``**name:** count`` lines, highest first; bad Config entries are skipped."""
    counts = [
        (user_id, data["lifted"])
        for user_id, data in all_users.items()
        if isinstance(data, dict) and isinstance(data.get("lifted"), int) and data["lifted"] > 0
    ]
    counts.sort(key=lambda item: item[1], reverse=True)
    return [f"{rank}. **{name_of(user_id)}:** {lifted}" for rank, (user_id, lifted) in enumerate(counts, 1)]


class Mjolnir(commands.Cog):
    """Attempt to lift Thor's hammer!"""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1242351245243535476356, force_registration=True)
        self.config.register_user(lifted=0)

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        await self.config.user_from_id(user_id).clear()

    @commands.command()
    @commands.guild_only()
    async def lifted(self, ctx: commands.Context) -> None:
        """Shows how many times you've lifted the hammer."""
        lifted = await self.config.user(ctx.author).lifted()
        await ctx.send(f"You have lifted Mjolnir {lifted} time{'' if lifted == 1 else 's'}.")

    @commands.command()
    @commands.guild_only()
    @commands.cooldown(1, 60.0, commands.BucketType.user)
    async def trylift(self, ctx: commands.Context) -> None:
        """Try and lift Thor's hammer!"""
        if random.randint(0, 100) < 95:  # same odds as the original, about 6%
            await ctx.send(random.choice(SAYINGS))
            return
        async with self.config.user(ctx.author).lifted.get_lock():
            lifted = await self.config.user(ctx.author).lifted()
            await self.config.user(ctx.author).lifted.set(lifted + 1)
        await ctx.send(
            "The sky opens up and a bolt of lightning strikes the ground\nYou are worthy. Hail, son of Odin."
        )

    @commands.command()
    @commands.guild_only()
    async def liftedboard(self, ctx: commands.Context) -> None:
        """Shows the leaderboard for those who have lifted the hammer."""

        def name_of(user_id: int) -> str:
            user = self.bot.get_user(user_id)
            return discord.utils.escape_markdown(user.display_name) if user else f"Unknown user ({user_id})"

        lines = leaderboard_lines(await self.config.all_users(), name_of)
        if not lines:
            await ctx.send(f"No one has lifted Mjolnir yet!\nWill you be the first? Try `{ctx.clean_prefix}trylift`")
            return
        pages = list(pagify("\n".join(lines), page_length=1000))
        if await ctx.embed_requested():
            colour = await ctx.embed_colour()
            pages = [
                discord.Embed(title="Mjolnir Leaderboard", description=page, colour=colour).set_footer(
                    text=f"Page {i}/{len(pages)}"
                )
                for i, page in enumerate(pages, 1)
            ]
        await SimpleMenu(pages).start(ctx)  # pyright: ignore[reportArgumentType]
