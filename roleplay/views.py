import contextlib
from collections.abc import Iterable

import discord
from redbot.core import commands

from . import const


class EmbedView(discord.ui.View):
    def __init__(
        self,
        embed: discord.Embed,
        label: str | None = None,
        style: discord.ButtonStyle = discord.ButtonStyle.primary,
    ):
        super().__init__(timeout=180)  # Optional: add a timeout for the view
        self.embed = embed
        self.label = label if label is not None else embed.title

        # Create the button with the given label and style
        self.button = discord.ui.Button(label=self.label, style=style)
        self.button.callback = self.show_settings
        self.add_item(self.button)

    async def show_settings(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=self.embed, ephemeral=True)


class ConsentView(discord.ui.View):
    """Yes/No buttons that only the members being asked can press.

    ``result`` becomes ``False`` on the first No (``declined_by`` is who pressed it),
    and ``True`` once every member has pressed Yes. It stays ``None`` on timeout.
    """

    def __init__(self, responders: Iterable[discord.abc.User], timeout: float = const.TIMEOUT) -> None:
        super().__init__(timeout=timeout)
        self.responder_ids = {user.id for user in responders}
        self.accepted: set[int] = set()
        self.result: bool | None = None
        self.declined_by: int | None = None
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id in self.responder_ids:
            return True
        await interaction.response.send_message("This question isn't for you.", ephemeral=True)
        return False

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.accepted.add(interaction.user.id)
        if self.accepted != self.responder_ids:
            await interaction.response.send_message("Thanks! Waiting for the others to answer.", ephemeral=True)
            return
        self.result = True
        await self.finish(interaction)

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.result = False
        self.declined_by = interaction.user.id
        await self.finish(interaction)

    async def finish(self, interaction: discord.Interaction) -> None:
        self.stop()
        self.disable_buttons()
        await interaction.response.edit_message(view=self)

    async def on_timeout(self) -> None:
        self.disable_buttons()
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

    def disable_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


async def request_consent(ctx: commands.Context, content: str, responders: Iterable[discord.abc.User]) -> ConsentView:
    """Ask ``responders`` a yes/no question with buttons and wait for their answer."""
    view = ConsentView(responders)
    view.message = await ctx.send(content, view=view)
    await view.wait()
    return view
