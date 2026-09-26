"""I'm Your Daddy

Responds to "I'm [blank]" or "I am [blank]" with "Hi, [blank]! I'm your daddy..."
"""

import random
import re

import discord

from .. import const
from .base_text_responder import BaseTextResponder


class ImDaddyResponder(BaseTextResponder):
    enabled = True
    # Match "i'm | i am" at the beginning of the message
    patterns = [r"\A(?:i'?\s?a?m\s+)"]
    ignore_case = True

    # respond to these users in UwU
    UWU = [const.RUFFIANA_ID, const.RADON_ID]

    async def respond(
        self,
        message: discord.Message,
        target: discord.Member,
        match: re.Match,
    ):
        if message.author.id in self.never_respond:
            return

        name = message.content[match.end() :].strip()

        chance = 50 / max(1, len(name))
        self.parent.logger.debug(f"{name} = {chance}% chance to respond")

        if message.author.id in self.always_respond or random.randint(0, 99) < chance:
            daddy_response = f"Hi, {name}! I'm your daddy..."
            # UwUCog is optional; look it up now so load order doesn't matter
            uwu_cog = self.bot.get_cog("UwUCog")
            if message.author.id in self.UWU and uwu_cog is not None:
                daddy_response = uwu_cog.translate(daddy_response)  # pyright: ignore[reportAttributeAccessIssue]

            await self.send_message(message, daddy_response, as_reply=True, delay=True)
