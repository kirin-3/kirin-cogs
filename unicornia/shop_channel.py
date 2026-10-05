"""The shop channel: the role shop posted as Components V2 messages, one per section, each with a buy menu.

Staff arrange it on the staff dashboard (dashboard/shop.py), which calls the methods here: sections with a heading, a
note and an optional banner, and the shop's items, each in at most one section. A role item shows the role's mention,
which Discord draws in the role's colour, so the post previews the colour without an image. The buy menu is a
DynamicItem, so it keeps working after a restart; it asks the member to confirm, then buys through the same
ShopSystem.purchase_item as `[p]shop buy`.

Every change to a section or a shop item edits the posted messages, including changes made with `[p]shop add`, `edit`
and `remove`. A section created after the shop was posted is posted at the end, where its place in the order is.
"""

import asyncio
import contextlib
import logging
import re
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeGuard, TypeVar

import discord
from discord import ui
from redbot.core.data_manager import cog_data_path

from .mixins import UnicorniaMixinBase
from .systems.shop_system import editor_problem, role_problem
from .types import ShopItem

log = logging.getLogger("red.kirin_cogs.unicornia.shop_channel")

MAX_ITEMS = 25  # Discord's limit for one dropdown
MAX_SECTION_NAME = 80
MAX_NOTE = 1000
MAX_ITEM_NAME = 100  # the same limit as [p]shop add
MAX_PRICE = 10**12
BANNER_MAX_BYTES = 8 * 1024 * 1024
BANNER_TYPES = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg", b"GIF87a": "gif", b"GIF89a": "gif"}
BANNER_EXTS = {"png", "jpg", "gif", "webp"}
ACCENT = discord.Colour(0x9D4EDD)
NO_PINGS = discord.AllowedMentions.none()
YES = "<a:zz_YesTick:729318762356015124>"
NO = "<a:zz_NoTick:729318761655435355>"

T = TypeVar("T")


def _is_id(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def clean_section(raw: object) -> dict[str, Any] | None:
    """A section from Config, with anything malformed dropped or defaulted; None if it has no name."""
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        return None
    items: list[int] = []
    stored = raw.get("items")
    for item_id in stored if isinstance(stored, list) else []:
        if _is_id(item_id) and item_id not in items:
            items.append(item_id)
    note = raw.get("note")
    return {
        "name": raw["name"],
        "note": note if isinstance(note, str) else "",
        "items": items[:MAX_ITEMS],
        "banner": raw["banner"] if raw.get("banner") in BANNER_EXTS else None,
        "message_id": raw["message_id"] if _is_id(raw.get("message_id")) else None,
        "position": raw["position"] if _is_id(raw.get("position")) else None,
    }


def banner_type(data: bytes) -> str | None:
    """The file extension for a PNG, JPEG, GIF or WebP image, by content; None for anything else."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return next((ext for magic, ext in BANNER_TYPES.items() if data.startswith(magic)), None)


def clean_name(text: str, limit: int, what: str) -> str:
    name = " ".join(text.split())
    if not name or len(name) > limit:
        raise ValueError(f"{what} needs 1 to {limit} characters.")
    return name


def clean_note(text: str) -> str:
    note = "\n".join(line.rstrip() for line in text.strip().splitlines())
    if len(note) > MAX_NOTE:
        raise ValueError(f"A note can be at most {MAX_NOTE} characters.")
    return note


def clean_price(price: int) -> int:
    if not 0 <= price <= MAX_PRICE:
        raise ValueError(f"The price must be between 0 and {MAX_PRICE:,}.")
    return price


class BuySelect(ui.DynamicItem[ui.Select], template=r"unicornia:shopbuy:(?P<id>\d+)"):
    def __init__(self, section_id: int, options: list[discord.SelectOption] | None = None):
        super().__init__(
            ui.Select(
                custom_id=f"unicornia:shopbuy:{section_id}",
                placeholder="Buy one of these",
                options=options or [],
            )
        )
        self.section_id = section_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: ui.Item, match: re.Match[str]) -> "BuySelect":
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        cog = interaction.client.get_cog("Unicornia")  # pyright: ignore[reportAttributeAccessIssue]
        member = interaction.user
        ready = isinstance(cog, ShopChannelMixin) and cog._check_systems_ready()
        if not ready or interaction.guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message("The shop isn't available right now.", ephemeral=True)
            return
        assert isinstance(cog, ShopChannelMixin)
        await cog.offer_shop_item(interaction, member, self.section_id, (self.item.values or [""])[0])


class BuyConfirm(ui.View):
    """The member's Buy / Cancel question for one item, on their ephemeral reply."""

    def __init__(self, cog: "ShopChannelMixin", item: ShopItem, what: str) -> None:
        super().__init__(timeout=120)
        self.cog, self.item, self.what = cog, item, what

    @ui.button(label="Buy", style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: ui.Button) -> None:
        member, guild = interaction.user, interaction.guild
        assert isinstance(member, discord.Member) and guild is not None
        self.stop()
        await interaction.response.defer()
        # ponytail: purchase_item looks the item up by index again; checking it here first leaves a moment where staff
        # could swap the item under that index, which a purchase-by-ID path in ShopSystem would close.
        current = await self.cog.shop_system.get_shop_item(guild.id, self.item["index"])
        if current is None or (current["id"], current["price"]) != (self.item["id"], self.item["price"]):
            text = f"{NO} This item changed while you were deciding. Pick it again from the menu."
        else:
            success, message, data = await self.cog.shop_system.purchase_item(member, guild.id, self.item["index"])
            symbol = await self.cog.config.currency_symbol()
            if success:
                text = (
                    f"{YES} You bought {self.what} for {self.item['price']:,} {symbol}. "
                    f"You have {data.get('remaining_balance', 0):,} {symbol} left."
                )
            else:
                text = f"{NO} {message}"
        await interaction.edit_original_response(content=text, view=None, allowed_mentions=NO_PINGS)

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", view=None)


class ShopChannelMixin(UnicorniaMixinBase):
    """The posted shop and its management, shared by the dashboard and the shop commands."""

    if TYPE_CHECKING:
        _shop_lock: asyncio.Lock

        def _check_systems_ready(self) -> bool: ...

    # --- reading ----------------------------------------------------------------------------------

    async def shop_sections(self, guild: discord.Guild) -> dict[int, dict[str, Any]]:
        """Every section by ID, in posting order, numbered 1, 2, 3... in `position`."""
        raw = await self.config.guild(guild).shop_sections()
        found = {}
        for key, value in raw.items() if isinstance(raw, dict) else ():
            section = clean_section(value)
            if str(key).isdigit() and section is not None:
                found[int(key)] = section
        ordered = dict(sorted(found.items(), key=lambda pair: (pair[1]["position"] or pair[0], pair[0])))
        for position, section in enumerate(ordered.values(), 1):
            section["position"] = position
        return ordered

    async def _shop_items(self, guild: discord.Guild) -> dict[int, ShopItem]:
        return {item["id"]: item for item in await self.shop_system.get_shop_items(guild.id)}

    def _item_role_problem(self, guild: discord.Guild, item: ShopItem) -> str | None:
        if item["type"] != self.db.shop.SHOP_TYPE_ROLE:
            return None
        role = guild.get_role(item["role_id"] or 0)
        return role_problem(role) if role else "Its role was deleted."

    async def shop_may_manage(self, member: discord.Member) -> bool:
        """The same gate as `[p]shop add`: the server owner, a bot owner, a Red admin, or Manage Roles."""
        return (
            member.id == member.guild.owner_id
            or member.guild_permissions.manage_roles
            or await self.bot.is_owner(member)
            or await self.bot.is_admin(member)
        )

    async def shop_overview(self, guild: discord.Guild, editor: discord.Member) -> dict[str, Any]:
        """The posted shop for the dashboard: the channel, the sections with their items, every shop item, and the
        roles the editor may sell (below their top role and the bot's, without moderator permissions), highest first."""
        sections = await self.shop_sections(guild)
        items = await self._shop_items(guild)
        channel_id = await self.config.guild(guild).shop_channel()
        channel = guild.get_channel(channel_id) if _is_id(channel_id) else None
        section_of = {item_id: section_id for section_id, section in sections.items() for item_id in section["items"]}

        def item_view(item: ShopItem) -> dict[str, Any]:
            role = guild.get_role(item["role_id"] or 0)
            requirement = guild.get_role(item["role_requirement"] or 0)
            return {
                "id": item["id"],
                "index": item["index"],
                "name": item["name"],
                "price": item["price"],
                "type": self.shop_system.get_type_name(item["type"]),
                "role_id": role.id if role else None,
                "role": role.name if role else "",
                "requirement_id": requirement.id if requirement else None,
                "requirement": requirement.name if requirement else "",
                "section_id": section_of.get(item["id"]),
                "problem": self._item_role_problem(guild, item),
            }

        return {
            "channel": {"id": channel.id, "name": channel.name} if channel else None,
            "channels": [
                {"id": c.id, "name": c.name}
                for c in guild.text_channels
                if c.permissions_for(guild.me).send_messages and c.permissions_for(guild.me).view_channel
            ],
            "sections": [
                {
                    "id": section_id,
                    "name": section["name"],
                    "note": section["note"],
                    "banner": section["banner"] is not None,
                    "full": len(section["items"]) >= MAX_ITEMS,
                    "url": f"https://discord.com/channels/{guild.id}/{channel.id}/{section['message_id']}"
                    if channel and section["message_id"]
                    else "",
                    "items": [item_view(items[item_id]) for item_id in section["items"] if item_id in items],
                }
                for section_id, section in sections.items()
            ],
            "items": [item_view(item) for item in items.values()],
            "roles": [
                {"id": role.id, "name": role.name}
                for role in reversed(guild.roles)
                if role_problem(role) is None and editor_problem(editor, role) is None
            ],
            "requirements": [
                {"id": role.id, "name": role.name} for role in reversed(guild.roles) if not role.is_default()
            ],
            "may_manage": await self.shop_may_manage(editor),
        }

    # --- the posted messages ----------------------------------------------------------------------

    def _shop_banner_path(self, guild: discord.Guild, section_id: int, ext: str) -> Path:
        return cog_data_path(self) / "shop_banners" / f"{guild.id}-{section_id}.{ext}"

    async def _shop_view(
        self, guild: discord.Guild, section_id: int, section: dict[str, Any], items: dict[int, ShopItem]
    ) -> tuple[ui.LayoutView, list[discord.File]]:
        """A section's message and its banner file. Items whose role can't be sold are left out."""
        view = ui.LayoutView(timeout=None)
        files = []
        if section["banner"]:
            name = f"banner.{section['banner']}"
            try:
                path = self._shop_banner_path(guild, section_id, section["banner"])
                data = await asyncio.to_thread(path.read_bytes)
            except OSError:
                log.warning("Banner of shop section %s in %s is missing", section_id, guild.id)
            else:
                files.append(discord.File(BytesIO(data), filename=name))
                view.add_item(ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{name}")))

        symbol = await self.config.currency_symbol()
        currency = await self.config.currency_name()
        prefix = (await self.bot.get_valid_prefixes(guild))[0]
        card = ui.Container(accent_colour=ACCENT)
        card.add_item(ui.TextDisplay(f"## {section['name']}\n{section['note']}".strip()))
        shown = [
            items[item_id]
            for item_id in section["items"]
            if item_id in items and self._item_role_problem(guild, items[item_id]) is None
        ]
        if shown:
            lines, options = [], []
            for item in shown:
                role = guild.get_role(item["role_id"] or 0) if item["type"] == self.db.shop.SHOP_TYPE_ROLE else None
                # A role item is labelled by its role: the shop imported from Nadeko named every item "-".
                options.append(
                    discord.SelectOption(
                        label=(role.name if role else item["name"])[:100],
                        value=str(item["index"]),
                        description=("Free" if item["price"] == 0 else f"{item['price']:,} {currency}")[:100],
                    )
                )
                what = role.mention if role else f"**{item['name']}**"
                price = "Free" if item["price"] == 0 else f"**{item['price']:,}** {symbol}"
                line = f"{what} ➥ {price} · `{prefix}shop buy {item['index']}`"
                if requirement := guild.get_role(item["role_requirement"] or 0):
                    line += f" · needs {requirement.mention}"
                lines.append(line)
            card.add_item(ui.Separator())
            card.add_item(ui.TextDisplay("\n".join(lines)))
            card.add_item(ui.ActionRow().add_item(BuySelect(section_id, options)))
        else:
            card.add_item(ui.TextDisplay("Nothing for sale here yet."))
        view.add_item(card)
        return view, files

    async def _refresh_shop(self, guild: discord.Guild) -> str | None:
        """Edit every posted section to match, and post sections that aren't up yet at the end. Hold _shop_lock.

        Returns why Discord refused a message, or None.
        """
        channel_id = await self.config.guild(guild).shop_channel()
        if not _is_id(channel_id):
            return None  # never posted
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return "the shop channel no longer exists. Post the shop again."
        sections, items = await self.shop_sections(guild), await self._shop_items(guild)
        problem = None
        for section_id, section in sections.items():
            view, files = await self._shop_view(guild, section_id, section, items)
            try:
                if section["message_id"]:
                    try:
                        message = channel.get_partial_message(section["message_id"])
                        await message.edit(view=view, attachments=files, allowed_mentions=NO_PINGS)
                        continue
                    except discord.NotFound:
                        pass  # deleted by hand: post it again
                for file in files:
                    file.reset()
                section["message_id"] = (await channel.send(view=view, files=files, allowed_mentions=NO_PINGS)).id
                await self._save_section(guild, section_id, section)
            except discord.HTTPException as exc:
                log.warning("Discord refused shop section %s in %s", section_id, guild.id, exc_info=True)
                problem = f"Discord refused the {section['name']} message ({exc.text or exc.status})."
        return problem

    async def refresh_shop_posts(self, guild: discord.Guild) -> str | None:
        """Bring the posted shop up to date after a shop item changed. Returns why it couldn't be, or None."""
        async with self._shop_lock:
            return await self._refresh_shop(guild)

    async def _save_section(self, guild: discord.Guild, section_id: int, section: dict[str, Any] | None) -> None:
        async with self.config.guild(guild).shop_sections() as stored:
            if section is None:
                stored.pop(str(section_id), None)
            else:
                stored[str(section_id)] = section

    async def _change_sections(self, guild: discord.Guild, change: Callable[[dict[int, dict[str, Any]]], T]) -> T:
        """Change the sections and update the posted shop. LookupError for a section that doesn't exist; ValueError
        with a message for staff otherwise, including when the change was saved but Discord refused the post."""
        async with self._shop_lock:
            sections = await self.shop_sections(guild)
            result = change(sections)
            await self.config.guild(guild).shop_sections.set({str(k): v for k, v in sections.items()})
            problem = await self._refresh_shop(guild)
        if problem:
            raise ValueError(f"Saved, but the shop channel wasn't updated: {problem}")
        return result

    @staticmethod
    def _section(sections: dict[int, dict[str, Any]], section_id: int) -> dict[str, Any]:
        if section_id not in sections:
            raise LookupError("That section doesn't exist anymore.")
        return sections[section_id]

    async def shop_post(self, guild: discord.Guild, channel: discord.TextChannel) -> None:
        """Post every section in order in the channel, replacing the shop posted before."""
        async with self._shop_lock:
            sections, items = await self.shop_sections(guild), await self._shop_items(guild)
            if not sections:
                raise ValueError("Create a section before posting the shop.")
            group = self.config.guild(guild)
            old_channel = guild.get_channel(await group.shop_channel() or 0)
            old = [section["message_id"] for section in sections.values() if section["message_id"]]
            posted: list[discord.Message] = []
            try:
                for section_id, section in sections.items():
                    view, files = await self._shop_view(guild, section_id, section, items)
                    posted.append(await channel.send(view=view, files=files, allowed_mentions=NO_PINGS))
                    section["message_id"] = posted[-1].id
            except discord.HTTPException as exc:
                for message in posted:
                    with contextlib.suppress(discord.HTTPException):
                        await message.delete()
                if isinstance(exc, discord.Forbidden):
                    raise ValueError(f"I can't post in #{channel.name} ({exc.text or exc.status}).") from exc
                raise ValueError(f"Discord refused the shop ({exc.text or exc.status}).") from exc
            await group.shop_channel.set(channel.id)
            await group.shop_sections.set({str(k): v for k, v in sections.items()})
        if isinstance(old_channel, discord.TextChannel):
            for message_id in old:
                with contextlib.suppress(discord.HTTPException):
                    await old_channel.get_partial_message(message_id).delete()

    # --- sections ---------------------------------------------------------------------------------

    async def shop_section_create(self, guild: discord.Guild, name: str, note: str = "") -> int:
        name, note = clean_name(name, MAX_SECTION_NAME, "A section name"), clean_note(note)

        def change(sections: dict[int, dict[str, Any]]) -> int:
            if any(s["name"].casefold() == name.casefold() for s in sections.values()):
                raise ValueError(f"There is already a section called {name}.")
            # A deleted section's number may come back; its message is gone.
            section_id = max(sections, default=0) + 1
            section = {"name": name, "note": note, "position": len(sections) + 1}
            sections[section_id] = clean_section(section) or {}
            return section_id

        return await self._change_sections(guild, change)

    async def shop_section_edit(self, guild: discord.Guild, section_id: int, name: str, note: str) -> None:
        name, note = clean_name(name, MAX_SECTION_NAME, "A section name"), clean_note(note)

        def change(sections: dict[int, dict[str, Any]]) -> None:
            section = self._section(sections, section_id)
            if any(s["name"].casefold() == name.casefold() for i, s in sections.items() if i != section_id):
                raise ValueError(f"There is already a section called {name}.")
            section.update(name=name, note=note)

        await self._change_sections(guild, change)

    async def shop_section_move(self, guild: discord.Guild, section_id: int, step: int) -> None:
        """Move a section one place up (-1) or down (1). It swaps messages with its neighbour, so the channel shows
        the new order without posting again. Nothing happens at either end."""

        def change(sections: dict[int, dict[str, Any]]) -> None:
            section = self._section(sections, section_id)
            order = list(sections)
            other = order.index(section_id) + step
            if 0 <= other < len(order):
                neighbour = sections[order[other]]
                for key in ("position", "message_id"):
                    section[key], neighbour[key] = neighbour[key], section[key]

        await self._change_sections(guild, change)

    async def shop_item_move(self, guild: discord.Guild, section_id: int, item_id: int, step: int) -> None:
        """Move an item one place up (-1) or down (1) in its section. Nothing happens at either end."""

        def change(sections: dict[int, dict[str, Any]]) -> None:
            items = self._section(sections, section_id)["items"]
            if item_id not in items:
                raise LookupError("That item isn't in this section anymore.")
            here = items.index(item_id)
            if 0 <= here + step < len(items):
                items[here], items[here + step] = items[here + step], items[here]

        await self._change_sections(guild, change)

    async def shop_section_banner(self, guild: discord.Guild, section_id: int, data: bytes | None) -> None:
        """Store a new banner (PNG, JPEG, GIF or WebP), or remove it with None."""
        ext = None
        if data is not None:
            if len(data) > BANNER_MAX_BYTES:
                raise ValueError(f"A banner can be at most {BANNER_MAX_BYTES // 1024 // 1024} MB.")
            if (ext := banner_type(data)) is None:
                raise ValueError("A banner must be a PNG, JPEG, GIF or WebP image.")
            if section_id not in await self.shop_sections(guild):
                raise LookupError("That section doesn't exist anymore.")
            path = self._shop_banner_path(guild, section_id, ext)
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, data)
        await self._change_sections(guild, lambda sections: self._section(sections, section_id).update(banner=ext))
        for other in BANNER_EXTS - {ext}:  # the banner this one replaced, if it had another type
            await asyncio.to_thread(self._shop_banner_path(guild, section_id, other).unlink, True)

    async def shop_section_delete(self, guild: discord.Guild, section_id: int) -> None:
        """Forget the section and delete its message and banner. Its items stay in the shop."""
        async with self._shop_lock:
            section = self._section(await self.shop_sections(guild), section_id)
            await self._save_section(guild, section_id, None)
        channel = guild.get_channel(await self.config.guild(guild).shop_channel() or 0)
        if isinstance(channel, discord.TextChannel) and section["message_id"]:
            with contextlib.suppress(discord.HTTPException):
                await channel.get_partial_message(section["message_id"]).delete()
        for ext in BANNER_EXTS:
            await asyncio.to_thread(self._shop_banner_path(guild, section_id, ext).unlink, True)

    # --- shop items -------------------------------------------------------------------------------

    def _check_role(self, editor: discord.Member, role: discord.Role) -> None:
        if problem := role_problem(role) or editor_problem(editor, role):
            raise ValueError(problem)

    @staticmethod
    def _place(sections: dict[int, dict[str, Any]], item_id: int, section_id: int | None) -> None:
        """Put the item in the section (None: in none), keeping its place if it is already there."""
        if section_id is not None and item_id in ShopChannelMixin._section(sections, section_id)["items"]:
            return
        for section in sections.values():
            if item_id in section["items"]:
                section["items"].remove(item_id)
        if section_id is not None:
            if len(sections[section_id]["items"]) >= MAX_ITEMS:
                raise ValueError(f"A section holds at most {MAX_ITEMS} items.")
            sections[section_id]["items"].append(item_id)

    async def shop_item_add(
        self,
        guild: discord.Guild,
        editor: discord.Member,
        name: str,
        price: int,
        role: discord.Role,
        requirement: discord.Role | None,
        section_id: int | None,
    ) -> int:
        """Add a role item to the shop, as `[p]shop add role` does, and place it in a section."""
        name, price = clean_name(name, MAX_ITEM_NAME, "An item name"), clean_price(price)
        self._check_role(editor, role)
        if section_id is not None:
            section = self._section(await self.shop_sections(guild), section_id)
            if len(section["items"]) >= MAX_ITEMS:
                raise ValueError(f"A section holds at most {MAX_ITEMS} items.")
        items = await self.shop_system.get_shop_items(guild.id)
        index = max((item["index"] for item in items), default=0) + 1
        item_id = await self.shop_system.add_shop_item(
            guild.id,
            index,
            price,
            name,
            editor.id,
            self.db.shop.SHOP_TYPE_ROLE,
            role.name,
            role.id,
            requirement.id if requirement else None,
        )
        await self._change_sections(guild, lambda sections: self._place(sections, item_id, section_id))
        return item_id

    async def shop_item_edit(
        self,
        guild: discord.Guild,
        editor: discord.Member,
        item_id: int,
        name: str,
        price: int,
        role: discord.Role | None,
        requirement: discord.Role | None,
        section_id: int | None,
    ) -> None:
        """Change an item, as `[p]shop edit` does. A role that changes is checked like a new one; None keeps the
        item's role. Setting a role makes the item a role item."""
        name, price = clean_name(name, MAX_ITEM_NAME, "An item name"), clean_price(price)
        item = (await self._shop_items(guild)).get(item_id)
        if item is None:
            raise LookupError("That shop item doesn't exist anymore.")
        changes: dict[str, Any] = {
            "name": name,
            "price": price,
            "role_requirement": requirement.id if requirement else None,
        }
        if role is not None and role.id != item["role_id"]:
            self._check_role(editor, role)
            changes.update(role_id=role.id, role_name=role.name, entry_type=self.db.shop.SHOP_TYPE_ROLE)
        if section_id is not None:
            self._section(await self.shop_sections(guild), section_id)
        await self.shop_system.update_shop_item(guild.id, item_id, **changes)
        await self._change_sections(guild, lambda sections: self._place(sections, item_id, section_id))

    async def shop_item_delete(self, guild: discord.Guild, item_id: int) -> None:
        """Remove the item from the shop and its section, as `[p]shop remove` does."""
        if not await self.shop_system.delete_shop_item(guild.id, item_id):
            raise LookupError("That shop item doesn't exist anymore.")
        await self._change_sections(guild, lambda sections: self._place(sections, item_id, None))

    # --- buying -----------------------------------------------------------------------------------

    async def offer_shop_item(
        self, interaction: discord.Interaction, member: discord.Member, section_id: int, value: str
    ) -> None:
        """Answer a pick from a section's buy menu with the item's price and a Buy / Cancel question."""
        guild = member.guild
        section = (await self.shop_sections(guild)).get(section_id)
        items = await self._shop_items(guild)
        item = next(
            (
                items[item_id]
                for item_id in (section["items"] if section else [])
                if item_id in items and str(items[item_id]["index"]) == value
            ),
            None,
        )
        if item is None or self._item_role_problem(guild, item):
            await interaction.response.send_message(f"{NO} That isn't for sale anymore.", ephemeral=True)
            return
        role = guild.get_role(item["role_id"] or 0) if item["type"] == self.db.shop.SHOP_TYPE_ROLE else None
        what = role.mention if role else f"**{item['name']}**"
        symbol = await self.config.currency_symbol()
        balance = await self.db.economy.get_spendable(member.id)
        await interaction.response.send_message(
            f"Buy {what} for {item['price']:,} {symbol}?\nYou have {balance:,} {symbol}.",
            view=BuyConfirm(self, item, what),
            ephemeral=True,
            allowed_mentions=NO_PINGS,
        )
