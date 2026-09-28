import contextlib
from collections.abc import Iterable

import discord
from redbot.core import commands

from . import const


class ConsentView(discord.ui.View):
    """Yes/No buttons that only the members being asked can press.

    ``result`` becomes ``False`` on the first No (``declined_by`` is who pressed it),
    and ``True`` once every member has pressed Yes. It stays ``None`` on timeout.
    ``request_consent`` deletes the question either way.
    """

    def __init__(self, responders: Iterable[discord.abc.User], timeout: float = const.TIMEOUT) -> None:
        super().__init__(timeout=timeout)
        self.responder_ids = {user.id for user in responders}
        self.accepted: set[int] = set()
        self.result: bool | None = None
        self.declined_by: int | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in self.responder_ids:
            return True
        await interaction.response.send_message("This question isn't for you.", ephemeral=True)
        return False

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await self.already_answered(interaction):
            return
        self.accepted.add(interaction.user.id)
        if self.accepted != self.responder_ids:
            await interaction.response.send_message("Thanks! Waiting for the others to answer.", ephemeral=True)
            return
        self.result = True
        await self.finish(interaction)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if await self.already_answered(interaction):
            return
        self.result = False
        self.declined_by = interaction.user.id
        await self.finish(interaction)

    async def already_answered(self, interaction: discord.Interaction) -> bool:
        """Presses can already be on their way when the answer is decided (or the question
        times out), and they run afterwards. They mustn't change it, so they're turned
        away here.

        This only awaits when turning a press away, so nothing else can run between a
        callback finding the question open and recording its answer.
        """
        if self.result is None and not self.is_finished():
            return False
        await interaction.response.send_message("This question is closed.", ephemeral=True)
        return True

    async def finish(self, interaction: discord.Interaction) -> None:
        self.stop()
        await interaction.response.defer()


async def request_consent(ctx: commands.Context, content: str, responders: Iterable[discord.abc.User]) -> ConsentView:
    """Ask ``responders`` a yes/no question with buttons and wait for their answer."""
    view = ConsentView(responders)
    message = await ctx.send(content, view=view)
    await view.wait()
    # answered or timed out, the question is only clutter now
    with contextlib.suppress(discord.HTTPException):
        await message.delete()
    return view
