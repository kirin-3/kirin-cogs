"""The Game Responder

Simple call/response responder that responds "I just lost The Game".
https://en.wikipedia.org/wiki/The_Game_(mind_game)
"""

import re

import discord

from .base_text_responder import BaseTextResponder


class TheGameResponder(BaseTextResponder):
    enabled = True
    patterns = [r"\bThe Game\b"]
    ignore_case = False

    cooldown_time = 120

    async def respond(
        self,
        message: discord.Message,
        target: discord.Member,
        match: re.Match,
    ):
        if message.author.id in self.never_respond:
            return

        await self.send_message(message, "I just lost The Game.", as_reply=True, delay=True)
