"""Cute Rate Responder

All users are 100% cute, except for Ruffiana.
"""

import re

import discord

from .. import const
from .base_rate_responder import BaseRateResponder


class CuteRate(BaseRateResponder):
    title = "❯ Cute Rate"
    description = "{target} is {rating}% cute"
    footer = None
    color = 0xFF8FC8
    bar_full = ("💗",)
    bar_empty = "🤍"

    user_overrides = {
        const.RUFFIANA_ID: {
            "rating": 0,
            "description": [
                "I'm sure {target} has a great...personality...",
                "{target}...?\n\nCute??..No.\n\nSorry, but no.",
                "{target}??\n\nLOL!!",
                "{target} is definitely *not* cute!",
            ],
        }
    }

    async def respond(self, message: discord.Message, target: discord.Member, match: re.Match):
        await self.send_rating(message, target, 100)
