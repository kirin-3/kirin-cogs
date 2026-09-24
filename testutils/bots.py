"""Bot doubles for dpytest-based tests."""

import discord
from discord.ext import commands


class RedLikeBot(commands.Bot):
    """A discord.py bot that dispatches ``message_without_command`` the way Red's bot does.

    Red parses each message once in ``process_commands`` and dispatches this event for
    messages that aren't commands, so cogs can listen to it instead of parsing again.
    """

    async def process_commands(self, message: discord.Message, /) -> None:
        ctx = None
        if not message.author.bot:
            ctx = await self.get_context(message)
            await self.invoke(ctx)
        if ctx is None or not ctx.valid:
            self.dispatch("message_without_command", message)
