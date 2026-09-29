"""Rich Rate Responder

Wallet plus bank from the Unicornia cog, on a log scale: 1,000 is 50% and 1,000,000 is 100%.
Without the cog it's the daily roll.
"""

import math
import re

import discord

from .base_rate_responder import BaseRateResponder


class RichRate(BaseRateResponder):
    title = "❯ Rich Rate"
    description = "{target} is {rating}% rich"
    color = 0xF1C40F
    bar_full = ("💰",)

    rating_overrides = {
        90: {"title": "❯ Filthy Rich", "description": "{target} is {rating}% rich. Swimming in slut points. 💸"},
        70: {"title": "❯ Loaded", "description": "{target} is {rating}% rich. Tips generously."},
        40: {"title": "❯ Comfortable", "description": "{target} is {rating}% rich. Can afford the nice snacks."},
        15: {"title": "❯ Scraping By", "description": "{target} is {rating}% rich. Checks the balance first."},
        0: {"title": "❯ Broke", "description": "{target} is {rating}% rich. Pockets full of lint."},
    }

    async def respond(self, message: discord.Message, target: discord.Member, match: re.Match):
        get_balance = getattr(self.bot.get_cog("Unicornia"), "get_balance", None)
        if get_balance is None:
            await super().respond(message, target, match)
            return
        wallet, bank = await get_balance(target.id)
        rating = min(100, round(100 * math.log10(1 + max(0, wallet + bank)) / 6))
        await self.send_rating(message, target, rating, footer="Going by wallet + bank.")
