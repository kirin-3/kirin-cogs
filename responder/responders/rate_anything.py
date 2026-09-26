"""Rate Anything

This is the default, all-purpose rate responder. It will respond with a
simple rating % and randomly selected gif from Tenor.
"""

import logging
import random
import re

import discord

from ..unicornia import web
from .base_rate_responder import BaseRateResponder

log = logging.getLogger("red.kirin_cogs.responder.rate_anything")


class RateAnything(BaseRateResponder):
    SUPPORTER_ROLE_IDS = {700121551483437128, 1458440559713718466}

    async def get_random_gif(self) -> str | None:
        # Search tenor for an appropriate thumbnail image; the embed falls back to the avatar without one
        search_term = self.topic.replace(" ", "-")
        try:
            gifs = await web.get_tenor_gifs(search_term)
        except Exception:
            log.warning("Tenor search for %r failed", search_term, exc_info=True)
            return None
        return random.choice(gifs) if gifs else None

    def is_approved(self, message: discord.Message) -> bool:
        author = message.author
        if not isinstance(author, discord.Member):
            return False
        return author.guild_permissions.administrator or any(
            role.id in self.SUPPORTER_ROLE_IDS for role in author.roles
        )

    async def respond(
        self,
        message: discord.Message,
        target: discord.Member,
        match: re.Match,
    ):
        # Check if the user is an approved user
        if not self.is_approved(message):
            return

        rating = self.get_rating()

        title = " ".join(word.capitalize() for word in self.topic.split())
        title = f"❯ {title} Rate"

        thumbnail = await self.get_random_gif() or target.display_avatar.url

        description = f"{target.display_name} is {rating}% {self.topic}"

        footer = r"The rate anything command is only available to supporters."

        await self.send_embed(
            message,
            title=title,
            description=description,
            thumbnail=thumbnail,
            footer=footer,
            delay=False,
        )
