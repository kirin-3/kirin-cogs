import functools
from redbot.core import commands

def systems_ready(func):
    async def predicate(ctx):
        if not ctx.cog._check_systems_ready():
            raise commands.UserFeedbackCheckFailure("❌ Systems are still initializing. Please try again in a moment.")
        return True
    return commands.check(predicate)(func)
