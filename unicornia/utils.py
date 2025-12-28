import functools
from redbot.core import commands

class SystemNotReady(commands.CheckFailure):
    pass

def systems_ready(func):
    async def predicate(ctx):
        if not ctx.cog._check_systems_ready():
            raise SystemNotReady()
        return True
    return commands.check(predicate)(func)
