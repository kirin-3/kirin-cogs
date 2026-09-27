"""
Unicorn stable commands for Unicornia: an idle game where unicorns earn coins while their owner is away.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import unicodedata
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_number
from redbot.core.utils.views import ConfirmView

from ..mixins import UnicorniaMixinBase
from ..systems import stable_card
from ..systems.stable_system import (
    BREEDS,
    DEFAULT_SETTINGS,
    MAX_NAME,
    PERKS,
    RARITIES,
    REGULAR_BREEDS,
    SEASONS,
    StableState,
    Unicorn,
    active_season,
    ascend_problem,
    collection_bonus,
)

if TYPE_CHECKING:
    from ..systems.stable_system import StableSystem

NO_MENTIONS = discord.AllowedMentions.none()


def clean_name(raw: str) -> str | None:
    """A unicorn name the card can draw: letters, numbers, punctuation and spaces. None if unusable."""
    name = " ".join(raw.split())
    if not name or len(name) > MAX_NAME:
        return None
    if not all(unicodedata.category(char)[0] in "LNPZ" for char in name):
        return None
    return name


def menu_label(slot: int, unicorn: Unicorn) -> str:
    """A unicorn as it appears in the card's menus, shinies marked."""
    return f"#{slot} {'✨ ' if unicorn.shiny else ''}{unicorn.label}"[:100]


async def card_file(system: StableSystem, member: discord.abc.User, state: StableState | None = None) -> discord.File:
    state = state or await system.state(member.id)
    image = await asyncio.to_thread(stable_card.render, state, member.display_name, active_season(time.time()))
    return discord.File(image, filename="stable.webp")


class StableView(discord.ui.View):
    """The owner's buttons under their stable card. Every press settles, acts and redraws the card."""

    def __init__(self, system: StableSystem, owner: discord.abc.User, state: StableState):
        super().__init__(timeout=300)
        self.system = system
        self.owner = owner
        self.message: discord.Message | None = None
        self._update(state)

    def _update(self, state: StableState) -> None:
        egg = state.egg_price
        self.hatch.label = "Stable full" if egg is None else f"Hatch egg · {egg:,}"
        self.hatch.disabled = egg is None
        box = state.next_box
        self.box.label = "Biggest box" if box is None else f"{box[0]}h box · {box[1]:,}"
        self.box.disabled = box is None
        self.collect.disabled = int(state.box) < 1
        self.ascend.disabled = ascend_problem(state) is not None

        options = [
            discord.SelectOption(
                label=menu_label(slot, unicorn),
                description=f"Level {unicorn.level} → {unicorn.level + 1} for {price:,}",
                value=str(unicorn.id),
            )
            for slot, unicorn in enumerate(state.unicorns, start=1)
            if (price := state.level_price(unicorn)) is not None
        ]
        self.upgrade.options = options or [discord.SelectOption(label="Nothing to upgrade", value="0")]
        self.upgrade.disabled = not options
        self.upgrade.placeholder = "Upgrade a unicorn…" if options else "Every unicorn is at the top level"

        self.release.options = [
            discord.SelectOption(
                label=menu_label(slot, unicorn), description=f"Level {unicorn.level}", value=str(unicorn.id)
            )
            for slot, unicorn in enumerate(state.unicorns, start=1)
        ] or [discord.SelectOption(label="No unicorns", value="0")]
        self.release.disabled = not state.unicorns

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner.id:
            return True
        await interaction.response.send_message("This isn't your stable. Open your own with `stable`.", ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                item.disabled = True
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

    async def _redraw(self, status: str, interaction: discord.Interaction | None = None) -> None:
        """Redraw the card through the button press that changed it, or straight on the message."""
        state = await self.system.state(self.owner.id)
        self._update(state)
        file = await card_file(self.system, self.owner, state)
        if interaction is not None:
            await interaction.edit_original_response(
                content=status, attachments=[file], view=self, allowed_mentions=NO_MENTIONS
            )
        elif self.message is not None:
            await self.message.edit(content=status, attachments=[file], view=self, allowed_mentions=NO_MENTIONS)

    @discord.ui.button(label="Collect", emoji="💰", style=discord.ButtonStyle.success)
    async def collect(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        paid = await self.system.collect(self.owner.id)
        await self._redraw(
            f"💰 Collected **{humanize_number(paid)}**." if paid else "The coin box is empty.", interaction
        )

    @discord.ui.button(label="Hatch egg", emoji="🥚", style=discord.ButtonStyle.primary)
    async def hatch(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        _breed, message = await self.system.hatch(self.owner.id)
        await self._redraw(message, interaction)

    @discord.ui.button(label="Bigger box", emoji="📦", style=discord.ButtonStyle.secondary)
    async def box(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer()
        _ok, message = await self.system.upgrade_box(self.owner.id)
        await self._redraw(message, interaction)

    @discord.ui.button(label="Ascend", emoji="✨", style=discord.ButtonStyle.secondary)
    async def ascend(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        state = await self.system.state(self.owner.id)
        question = (
            f"Ascend? Your {len(state.unicorns)} unicorns trot off and you keep the **{int(state.box):,}** coins "
            f"in your box, your coin box size and your collection, and reach ascension "
            f"{state.ascensions + 1}: **+10% earnings**, but prices rise **20%**."
        )
        if any(u.shiny for u in state.unicorns):
            question += "\n✨ Your stable includes a **shiny** — it will be lost!"
        await interaction.response.send_message(
            question, view=ConfirmChoice(self, "Ascend", self._ascend_now), ephemeral=True
        )

    async def _ascend_now(self) -> str:
        _ok, message = await self.system.ascend(self.owner.id)
        return message

    @discord.ui.select(placeholder="Upgrade a unicorn…", row=1)
    async def upgrade(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        await interaction.response.defer()
        _ok, message = await self.system.upgrade(self.owner.id, int(select.values[0]))
        await self._redraw(message, interaction)

    @discord.ui.select(placeholder="Release a unicorn…", row=2)
    async def release(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        state = await self.system.state(self.owner.id)
        found = next(
            ((slot, u) for slot, u in enumerate(state.unicorns, start=1) if u.id == int(select.values[0])), None
        )
        if found is None:
            await interaction.response.send_message("That unicorn isn't in your stable any more.", ephemeral=True)
            return
        slot, unicorn = found
        question = (
            f"Release **#{slot} {unicorn.safe_label}** (level {unicorn.level})? You get nothing back for it, "
            "but what it already earned stays in your coin box."
        )
        if unicorn.shiny:
            question += "\n✨ This one is **shiny** — it will be lost!"
        await interaction.response.send_message(
            question, view=ConfirmChoice(self, "Release", self._release_now(unicorn)), ephemeral=True
        )

    def _release_now(self, unicorn: Unicorn) -> Callable[[], Awaitable[str]]:
        async def run() -> str:
            if await self.system.release(self.owner.id, unicorn.id):
                return f"👋 **{unicorn.safe_label}** trotted off into the sunset."
            return "That unicorn isn't in your stable any more."

        return run


class ConfirmChoice(discord.ui.View):
    """The owner's private yes/no before something from their card goes ahead."""

    def __init__(self, stable: StableView, confirm_label: str, action: Callable[[], Awaitable[str]]):
        super().__init__(timeout=60)
        self.stable = stable
        self.action = action
        self.confirm.label = confirm_label

    @discord.ui.button(label="Release", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        status = await self.action()
        await interaction.response.edit_message(content=status, view=None, allowed_mentions=NO_MENTIONS)
        await self.stable._redraw(status)

    @discord.ui.button(label="Keep", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Kept it.", view=None)
        if self.stable.message is not None:  # clears the choice left showing in the menu
            with contextlib.suppress(discord.HTTPException):
                await self.stable.message.edit(view=self.stable)


class StableCommands(UnicorniaMixinBase):
    """The unicorn stable idle game"""

    @commands.hybrid_group(name="stable", fallback="view", invoke_without_command=True)  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.bot_has_permissions(attach_files=True)
    async def stable_group(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        """
        Your unicorn stable: unicorns earn coins while you're away.

        Hatch eggs for unicorns, upgrade them to earn more, and collect the coin box before it fills up.
        Discover breeds, find shinies and, once every stall holds a level-10 unicorn, ascend for a
        permanent earnings boost. Anyone can look at someone else's stable; only the owner gets the buttons.

        **Syntax**
        `[p]stable [member]`
        """
        owner = member or ctx.author
        state = await self.stable_system.state(owner.id)
        file = await card_file(self.stable_system, owner, state)
        if owner.id != ctx.author.id:
            await ctx.send(file=file)
            return
        view = StableView(self.stable_system, owner, state)
        view.message = await ctx.send(file=file, view=view)

    @stable_group.command(name="name")
    async def stable_name(self, ctx: commands.Context, slot: int, *, name: str | None = None) -> None:
        """
        Name one of your unicorns, or leave the name out to go back to its breed.

        Up to 20 letters, numbers, spaces and punctuation.

        **Syntax**
        `[p]stable name <number> [name]`
        """
        cleaned = None
        if name is not None:
            cleaned = clean_name(name)
            if cleaned is None:
                await ctx.send(f"Names can be up to {MAX_NAME} letters, numbers, spaces and punctuation.")
                return
        _ok, message = await self.stable_system.rename(ctx.author.id, slot, cleaned)
        await ctx.send(message, allowed_mentions=NO_MENTIONS)

    @stable_group.command(name="release")
    async def stable_release(self, ctx: commands.Context, slot: int) -> None:
        """
        Let one of your unicorns go, to make room for a new egg.

        You get nothing back for it, but what it already earned stays in your coin box. The breed
        stays in your collection.
        **Syntax**
        `[p]stable release <number>`
        """
        state = await self.stable_system.state(ctx.author.id)
        if not 1 <= slot <= len(state.unicorns):
            await ctx.send(f"You don't have a unicorn #{slot}.")
            return
        unicorn = state.unicorns[slot - 1]
        question = f"Release **#{slot} {unicorn.safe_label}** (level {unicorn.level})? You get nothing back for it."
        if unicorn.shiny:
            question += "\n✨ This one is **shiny** — it will be lost!"
        view = ConfirmView(ctx.author, disable_buttons=True)
        view.message = await ctx.send(question, view=view, allowed_mentions=NO_MENTIONS)
        await view.wait()
        if not view.result:
            await ctx.send("Kept it.")
            return
        if await self.stable_system.release(ctx.author.id, unicorn.id):
            await ctx.send(f"👋 **{unicorn.safe_label}** trotted off into the sunset.", allowed_mentions=NO_MENTIONS)
        else:
            await ctx.send("That unicorn isn't in your stable any more.")

    @stable_group.command(name="collection")
    async def stable_collection(self, ctx: commands.Context) -> None:
        """
        Every unicorn breed you have ever hatched, and what each one's perk does.

        Breeds you haven't hatched yet stay secret. Discovering both breeds of a rarity, and then all
        ten, permanently earns you more.
        **Syntax**
        `[p]stable collection`
        """
        state = await self.stable_system.state(ctx.author.id)
        shinies = ", ".join(sorted(BREEDS[breed].name for breed in state.shiny_found))
        embed = discord.Embed(
            title=f"📖 {ctx.author.display_name}'s collection",
            description=(
                f"{state.found}/{len(REGULAR_BREEDS)} breeds found  ·  collection bonus "
                f"+{collection_bonus(state.discovered):.0%}\n"
                + (f"✨ Shiny found: {shinies}" if shinies else "✨ No shinies hatched yet")
            ),
            color=discord.Color.pink(),
        )
        for rarity in ("common", "uncommon", "rare", "epic", "legendary"):
            lines = []
            for key, breed in BREEDS.items():
                if breed.rarity != rarity:
                    continue
                if key in state.discovered:
                    shiny = " ✨" if key in state.shiny_found else ""
                    lines.append(f"✅ **{breed.name}**{shiny} — {PERKS[key].description}")
                else:
                    lines.append("❔ ???")
            embed.add_field(name=RARITIES[rarity].name, value="\n".join(lines), inline=True)
        seasonal = [key for key in SEASONS if key in state.discovered]
        if seasonal:
            lines = [
                f"✅ **{BREEDS[key].name}**{' ✨' if key in state.shiny_found else ''} — 25 a day per level"
                for key in seasonal
            ]
            embed.add_field(name="Seasonal", value="\n".join(lines), inline=True)
        present = {u.breed for u in state.unicorns}
        active = [(BREEDS[key].name, PERKS[key].description) for key in sorted(present) if key in PERKS]
        if active:
            embed.add_field(
                name="Active in your stable",
                value="\n".join(f"**{name}** — {description}" for name, description in active),
                inline=False,
            )
        await ctx.send(embed=embed)

    @stable_group.command(name="ascend")
    async def stable_ascend(self, ctx: commands.Context) -> None:
        """
        Ascend: empty your stable of ten level-10 unicorns for a permanent boost.

        The coin box pays out, your unicorns trot off, and you keep your coins, your coin box size
        and your collection. Each ascension earns you 10% more and raises prices 20%.
        **Syntax**
        `[p]stable ascend`
        """
        state = await self.stable_system.state(ctx.author.id)
        problem = ascend_problem(state)
        if problem is not None:
            await ctx.send(problem)
            return
        question = (
            f"Ascend? Your {len(state.unicorns)} unicorns trot off and you keep the **{int(state.box):,}** coins "
            f"in your box, your coin box size and your collection, and reach ascension "
            f"{state.ascensions + 1}: **+10% earnings**, but prices rise **20%**."
        )
        if any(u.shiny for u in state.unicorns):
            question += "\n✨ Your stable includes a **shiny** — it will be lost!"
        view = ConfirmView(ctx.author, disable_buttons=True)
        view.message = await ctx.send(question, view=view, allowed_mentions=NO_MENTIONS)
        await view.wait()
        if not view.result:
            await ctx.send("Not yet, then.")
            return
        _ok, message = await self.stable_system.ascend(ctx.author.id)
        await ctx.send(message, allowed_mentions=NO_MENTIONS)

    @stable_group.command(name="top")
    async def stable_top(self, ctx: commands.Context) -> None:
        """
        The stables that earn the most a day.

        **Syntax**
        `[p]stable top`
        """
        assert ctx.guild is not None
        ranked = await self.stable_system.top({member.id for member in ctx.guild.members})
        if not ranked:
            await ctx.send("Nobody has a unicorn yet. Hatch one with `stable`.")
            return
        lines = []
        for place, (user_id, per_day, ascensions) in enumerate(ranked, start=1):
            member = ctx.guild.get_member(user_id)
            name = discord.utils.escape_markdown(member.display_name) if member else str(user_id)
            stars = f"  ·  ★ {ascensions}" if ascensions else ""
            lines.append(f"**{place}.** {name}: {humanize_number(round(per_day))} a day{stars}")
        embed = discord.Embed(title="🦄 Top stables", description="\n".join(lines), color=discord.Color.pink())
        await ctx.send(embed=embed)

    @commands.command(name="stableset")  # type: ignore[arg-type]
    @commands.is_owner()
    async def stableset(self, ctx: commands.Context, key: str | None = None, value: float | None = None) -> None:
        """
        Show or tune the stable's prices and earnings.

        `egg_price` is the first egg; each unicorn owned multiplies it by `egg_growth`. `level_price` is level 1 to 2;
        each level multiplies it by `level_growth`. `earn_rate` multiplies every unicorn's earnings.

        **Syntax**
        `[p]stableset [key value]`
        """
        if key is None or value is None:
            settings = await self.stable_system.settings()
            lines = [
                f"`{name}`: {settings[name]:g} (default {default:g})" for name, default in DEFAULT_SETTINGS.items()
            ]
            await ctx.send("\n".join(lines))
            return
        if key not in DEFAULT_SETTINGS or value <= 0:
            await ctx.send(f"Use one of {', '.join(f'`{name}`' for name in DEFAULT_SETTINGS)} and a value above 0.")
            return
        async with self.config.stable_settings() as settings:
            settings[key] = value
        await ctx.send(f"`{key}` is now {value:g}.")
