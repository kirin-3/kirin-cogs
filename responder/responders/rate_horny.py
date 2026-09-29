"""Horny Rate Responder

The share of lewd roleplay actions a member gave or got, from the Roleplay cog's counts.
Members without counts (or with its Untracked setting on) get the daily roll instead.
"""

import re

import discord

from .base_rate_responder import BaseRateResponder

LEWD_ACTIONS = frozenset(
    {"cunnilingus", "fuck", "grope", "lick", "nipplesuck", "peg", "ride", "siton", "spank", "suck"}
)


class HornyRate(BaseRateResponder):
    title = "❯ Horny Rate"
    description = "{target} is {rating}% horny"
    color = 0xFF4500
    bar_full = ("🔥",)

    rating_overrides = {
        90: {
            "title": "❯ Down Horrendous",
            "description": [
                "{target} is {rating}% horny. Straight to horny jail. 🚨",
                "{target} is {rating}% horny. Someone get the hose.",
            ],
        },
        70: {"title": "❯ Down Bad", "description": "{target} is {rating}% horny. Down bad, and not hiding it."},
        40: {"title": "❯ Thirsty", "description": "{target} is {rating}% horny. Thirsty, but still functional."},
        15: {"title": "❯ A Little Warm", "description": "{target} is {rating}% horny. Warm under the collar."},
        0: {"title": "❯ Pure", "description": "{target} is {rating}% horny. Pure as fresh snow. For now."},
    }

    async def respond(self, message: discord.Message, target: discord.Member, match: re.Match):
        action_counts = getattr(self.bot.get_cog("Roleplay"), "action_counts", None)
        counts = await action_counts(target.id) if action_counts else None
        if not counts:
            await super().respond(message, target, match)
            return
        lewd = sum(n for action, n in counts.items() if action in LEWD_ACTIONS)
        await self.send_rating(
            message, target, round(100 * lewd / counts.total()), footer="Calculated from roleplay stats."
        )
