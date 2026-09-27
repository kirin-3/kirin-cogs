"""Question cards with buttons, live votes, the suggestion modal and the staff review buttons."""

import contextlib
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .conversationgames import ConversationGames

Question = str | tuple[str, str]

NAMES = {"truth": "Truth", "dare": "Dare", "wyr": "Would you rather...", "nhie": "Never have I ever..."}
COLORS = {"truth": 0x5865F2, "dare": 0xED4245, "wyr": 0xFEE75C, "nhie": 0xEB459E}
CARD_TIMEOUT = 15 * 60


def card_embed(
    kind: str, question: Question, asker: discord.abc.User, target: discord.abc.User | None
) -> discord.Embed:
    embed = discord.Embed(title=NAMES[kind], color=COLORS[kind])
    if isinstance(question, tuple):
        embed.description = f"🅰️ {question[0]}\n\n🅱️ {question[1]}?"
    else:
        embed.description = question
    if target is not None:
        verb = "dares" if kind == "dare" else "asks"
        embed.set_author(name=f"{asker.display_name} {verb} {target.display_name}", icon_url=target.display_avatar.url)
    else:
        embed.set_footer(text=f"For {asker.display_name}", icon_url=asker.display_avatar.url)
    return embed


class _Card(discord.ui.View):
    """A question card. Its buttons stop working after 15 minutes, keeping any vote counts."""

    def __init__(self, cog: "ConversationGames", kind: str) -> None:
        super().__init__(timeout=CARD_TIMEOUT)
        self.cog = cog
        self.kind = kind
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):  # deleted, or the channel is gone
                await self.message.edit(view=self)

    async def suggest(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(SuggestModal(self.cog, self.kind))


class TruthOrDareCard(_Card):
    """Whoever presses Truth, Dare or Random gets a new card of their own."""

    @discord.ui.button(label="Truth", style=discord.ButtonStyle.primary)
    async def truth(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.post(interaction, "truth", interaction.user)

    @discord.ui.button(label="Dare", style=discord.ButtonStyle.danger)
    async def dare(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.post(interaction, "dare", interaction.user)

    @discord.ui.button(label="Random", style=discord.ButtonStyle.secondary)
    async def random(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.post(interaction, "tod", interaction.user)

    @discord.ui.button(label="Suggest one", style=discord.ButtonStyle.secondary, emoji="💡")
    async def suggest_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.suggest(interaction)


class VoteCard(_Card):
    """Would you rather and never have I ever: one vote each, pressed again to take it back, counted live."""

    CHOICES = {"wyr": ("🅰️", "🅱️"), "nhie": ("🙋 I have", "😇 I haven't")}

    def __init__(self, cog: "ConversationGames", kind: str) -> None:
        super().__init__(cog, kind)
        self.votes: dict[int, int] = {}  # user ID -> 0 or 1
        self._label()

    def _label(self) -> None:
        for choice, button in enumerate((self.first, self.second)):
            count = sum(1 for vote in self.votes.values() if vote == choice)
            button.label = f"{self.CHOICES[self.kind][choice]} {count}"

    async def _vote(self, interaction: discord.Interaction, choice: int) -> None:
        if self.votes.get(interaction.user.id) == choice:
            del self.votes[interaction.user.id]
        else:
            self.votes[interaction.user.id] = choice
        self._label()
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="first", style=discord.ButtonStyle.primary)
    async def first(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._vote(interaction, 0)

    @discord.ui.button(label="second", style=discord.ButtonStyle.primary)
    async def second(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self._vote(interaction, 1)

    @discord.ui.button(label="Another", style=discord.ButtonStyle.secondary)
    async def another(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.post(interaction, self.kind, interaction.user)

    @discord.ui.button(label="Suggest one", style=discord.ButtonStyle.secondary, emoji="💡")
    async def suggest_button(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.suggest(interaction)


class SuggestModal(discord.ui.Modal):
    def __init__(self, cog: "ConversationGames", kind: str) -> None:
        titles = {"truth": "a truth", "dare": "a dare", "wyr": "a would you rather", "nhie": "a never have I ever"}
        super().__init__(title=f"Suggest {titles[kind]}")
        self.cog = cog
        self.kind = kind
        self.inputs: list[discord.ui.TextInput] = []
        if kind == "wyr":
            fields = [("first", "Would you rather...", "eat only pizza"), ("second", "...or", "never eat pizza again")]
            for custom_id, label, placeholder in fields:
                self.inputs.append(
                    discord.ui.TextInput(custom_id=custom_id, label=label, placeholder=placeholder, max_length=150)
                )
        else:
            label = "Never have I ever..." if kind == "nhie" else f"Your {kind}"
            self.inputs.append(
                discord.ui.TextInput(
                    custom_id="question", label=label, style=discord.TextStyle.paragraph, max_length=300
                )
            )
        for text_input in self.inputs:
            self.add_item(text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.submit(interaction, self.kind, [text_input.value for text_input in self.inputs])


class ReviewView(discord.ui.View):
    """Approve and Deny on suggestions in the review channel. Persistent: the question is read back from the post."""

    def __init__(self, cog: "ConversationGames") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="conversationgames:approve")
    async def approve(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.review(interaction, approved=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, custom_id="conversationgames:deny")
    async def deny(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.review(interaction, approved=False)


def review_embed(kind: str, question: Question, suggester: discord.abc.User) -> discord.Embed:
    embed = discord.Embed(title=f"Suggested: {NAMES[kind]}", color=COLORS[kind])
    if isinstance(question, tuple):
        embed.add_field(name="🅰️", value=question[0], inline=False)
        embed.add_field(name="🅱️", value=question[1], inline=False)
    else:
        embed.description = question
    embed.set_author(name=suggester.display_name, icon_url=suggester.display_avatar.url)
    embed.set_footer(text=f"Kind: {kind}")
    return embed


def read_review(embed: discord.Embed) -> tuple[str, Question] | None:
    """The kind and question a review post is about, or None if it can't be read."""
    kind = (embed.footer.text or "").removeprefix("Kind: ")
    if kind == "wyr" and len(embed.fields) == 2 and embed.fields[0].value and embed.fields[1].value:
        return kind, (embed.fields[0].value, embed.fields[1].value)
    if kind in NAMES and kind != "wyr" and embed.description:
        return kind, embed.description
    return None
