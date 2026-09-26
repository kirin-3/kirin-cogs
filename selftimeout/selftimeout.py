import contextlib
from datetime import timedelta

import discord
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import humanize_timedelta
from redbot.core.utils.views import ConfirmView

# Discord caps timeouts at 28 days.
MAX_BREAK = timedelta(days=28)


def break_blocker(member: discord.Member) -> str | None:
    """Return why the bot can't time this member out, or None if it can."""
    guild = member.guild
    if member.id == guild.owner_id:
        return "Discord doesn't let anyone time out the server owner."
    if member.guild_permissions.administrator:
        return "Discord doesn't let bots time out administrators."
    if not guild.me.guild_permissions.moderate_members:
        return "I need the **Timeout Members** permission to do that."
    if member.top_role >= guild.me.top_role:
        return "Your top role is above mine, so I can't time you out."
    return None


class SelfTimeout(commands.Cog):
    """Let members time themselves out for a break."""

    def __init__(self, bot: Red):
        self.bot = bot

    @commands.hybrid_command(name="break")
    @commands.guild_only()
    async def break_(
        self,
        ctx: commands.GuildContext,
        duration: timedelta = commands.parameter(
            converter=commands.get_timedelta_converter(
                minimum=timedelta(minutes=1), maximum=MAX_BREAK, default_unit="minutes"
            )
        ),
    ) -> None:
        """Time yourself out for a break, up to 28 days.

        Examples: `1h`, `3 days`, `2w`. A bare number is minutes.
        """
        if blocker := break_blocker(ctx.author):
            await ctx.send(blocker, ephemeral=True)
            return

        view = ConfirmView(ctx.author, timeout=60)
        view.confirm_button.label = "Take a break"
        view.confirm_button.style = discord.ButtonStyle.red
        view.dismiss_button.label = "Cancel"
        until = discord.utils.utcnow() + duration
        view.message = msg = await ctx.send(
            f"You'll be timed out for **{humanize_timedelta(timedelta=duration)}**, until "
            f"{discord.utils.format_dt(until)}. You won't be able to chat, react or join voice "
            "until then. Continue?",
            view=view,
            ephemeral=True,
        )
        await view.wait()

        if view.result:
            try:
                await ctx.author.timeout(duration, reason="Requested a break with the break command")
            except discord.HTTPException:
                with contextlib.suppress(discord.HTTPException):
                    await msg.edit(content="I couldn't time you out. Nothing changed.", view=None)
                return

        with contextlib.suppress(discord.HTTPException):
            await msg.delete()
        # Slash invocations have no real message to delete.
        if ctx.interaction is None:
            with contextlib.suppress(discord.HTTPException):
                await ctx.message.delete()
