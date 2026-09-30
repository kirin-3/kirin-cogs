"""Self-assigned roles from dropdown menus, one message per category.

Admins create and post categories with commands. Roles are added and removed with commands or on the staff dashboard
(dashboard/selfroles.py), which call the same methods, so both follow the same rules. A posted category is one
Components V2 message: its banner, then a card with the heading, the role list, a dropdown and a Clear button. The
dropdown and button are DynamicItems: they keep working after a restart and read the category from Config when used.

A role can only be on a menu while it is below the bot's top role and has no moderator permissions, and the person
adding it must be above it. The first two are checked again every time someone picks, so a role that gains
permissions later stops being handed out.
"""

import asyncio
import contextlib
import copy
import logging
import re
import unicodedata
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import Any, TypeGuard

import discord
from discord import ui
from redbot.core import Config, commands
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import humanize_list, pagify

log = logging.getLogger("red.kirin_cogs.selfroles")

MAX_OPTIONS = 25  # Discord's limit for one dropdown
MAX_NAME = 80
MAX_NOTE = 100  # Discord's limit for the text under a dropdown option
BANNER_MAX_BYTES = 8 * 1024 * 1024
ACCENT = discord.Colour(0x9D4EDD)
NO_PINGS = discord.AllowedMentions.none()
CUSTOM_EMOJI = re.compile(r"<a?:\w{2,32}:(\d{15,21})>")
EMOJI_NAME = re.compile(r":(\w{2,32}):")
CHANNEL_MENTION = re.compile(r"<#(\d{15,21})>")
# A self-assigned role must not carry any of these.
BLOCKED_PERMISSIONS = discord.Permissions.elevated() | discord.Permissions(
    mention_everyone=True,
    view_audit_log=True,
    manage_nicknames=True,
    manage_events=True,
    move_members=True,
    mute_members=True,
    deafen_members=True,
)
BANNER_TYPES = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg", b"GIF87a": "gif", b"GIF89a": "gif"}
BANNER_EXTS = {"png", "jpg", "gif", "webp"}


class _Gone(Exception):
    """The channel a menu was posted in no longer exists."""


def _is_id(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def clean_category(raw: object) -> dict[str, Any] | None:
    """A category from Config, with anything malformed dropped or defaulted; None if it has no name."""
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        return None
    roles = []
    entries = raw.get("roles")
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict) and _is_id(entry.get("id")) and entry["id"] not in {r["id"] for r in roles}:
            emoji, note = entry.get("emoji"), entry.get("note")
            roles.append(
                {
                    "id": entry["id"],
                    "emoji": emoji if isinstance(emoji, str) else "",
                    "note": note[:MAX_NOTE] if isinstance(note, str) else "",
                }
            )
    max_picks = raw.get("max")
    return {
        "name": raw["name"],
        "max": max_picks if _is_id(max_picks) and max_picks <= MAX_OPTIONS else 1,
        "roles": roles,
        "channel_id": raw["channel_id"] if _is_id(raw.get("channel_id")) else None,
        "message_id": raw["message_id"] if _is_id(raw.get("message_id")) else None,
        "banner": raw["banner"] if raw.get("banner") in BANNER_EXTS else None,
    }


def banner_type(data: bytes) -> str | None:
    """The file extension for a PNG, JPEG, GIF or WebP image, by content; None for anything else."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return next((ext for magic, ext in BANNER_TYPES.items() if data.startswith(magic)), None)


def is_unicode_emoji(text: str) -> bool:
    """Whether the text is made only of emoji characters.

    ponytail: a character-class check, not the full emoji list. Discord has the final say: a menu it refuses is
    rolled back (see SelfRoles._change).
    """
    if not text or len(text) > 16:
        return False
    keycap = "\u20e3" in text  # 1️⃣, #️⃣, *️⃣
    for char in text:
        if char in "#*0123456789":
            if not keycap:
                return False
        elif unicodedata.category(char) not in ("So", "Sk", "Mn", "Me", "Cf"):
            return False
    return keycap or any(unicodedata.category(char) == "So" for char in text)


def role_problem(guild: discord.Guild, role: discord.Role) -> str | None:
    """Why a menu may not hand out this role, or None."""
    if role.is_default() or role.managed:
        return f"{role.name} is managed by Discord or an integration."
    if not role.is_assignable():
        return f"{role.name} is not below my top role."
    risky = [name for name, value in role.permissions if value and getattr(BLOCKED_PERMISSIONS, name)]
    if risky:
        return f"{role.name} has moderator permissions ({humanize_list([n.replace('_', ' ') for n in risky])})."
    return None


def editor_problem(editor: discord.Member, role: discord.Role) -> str | None:
    """Staff may only put roles on a menu that they could give out themselves."""
    if editor.id != editor.guild.owner_id and role >= editor.top_role:
        return f"{role.name} is not below your top role."
    return None


def limit_text(max_picks: int) -> str:
    return "Pick one." if max_picks == 1 else f"Pick up to {max_picks}."


def clean_note(text: str) -> str:
    """A note as stored: one line, at most MAX_NOTE characters."""
    note = " ".join(text.split())
    if len(note) > MAX_NOTE:
        raise ValueError(f"A note can be at most {MAX_NOTE} characters.")
    return note


def plain_note(guild: discord.Guild, note: str) -> str:
    """The note for the dropdown, which shows text as it is: channel mentions become #name."""

    def channel(match: re.Match[str]) -> str:
        found = guild.get_channel_or_thread(int(match[1]))
        return f"#{found.name}" if found else "#deleted-channel"

    return CHANNEL_MENTION.sub(channel, note)[:MAX_NOTE]


class PickSelect(ui.DynamicItem[ui.Select], template=r"selfroles:pick:(?P<id>\d+)"):
    def __init__(self, category_id: int, options: list[discord.SelectOption] | None = None, max_values: int = 1):
        super().__init__(
            ui.Select(
                custom_id=f"selfroles:pick:{category_id}",
                placeholder="Choose your roles" if max_values > 1 else "Choose your role",
                max_values=max_values,
                options=options or [],
            )
        )
        self.category_id = category_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: ui.Item, match: re.Match[str]
    ) -> "PickSelect":
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        chosen = [int(value) for value in self.item.values if value.isdigit()]
        await _pick(interaction, self.category_id, chosen)


class ClearButton(ui.DynamicItem[ui.Button], template=r"selfroles:clear:(?P<id>\d+)"):
    def __init__(self, category_id: int):
        super().__init__(
            ui.Button(label="Clear", style=discord.ButtonStyle.secondary, custom_id=f"selfroles:clear:{category_id}")
        )
        self.category_id = category_id

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: ui.Item, match: re.Match[str]
    ) -> "ClearButton":
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await _pick(interaction, self.category_id, [])


async def _pick(interaction: discord.Interaction, category_id: int, chosen: list[int]) -> None:
    cog = interaction.client.get_cog("SelfRoles")  # pyright: ignore[reportAttributeAccessIssue]
    guild, member = interaction.guild, interaction.user
    if not isinstance(cog, SelfRoles) or guild is None or not isinstance(member, discord.Member):
        await interaction.response.send_message("This menu isn't available right now.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    category = (await cog.categories(guild)).get(category_id)
    if category is None:
        text = "This menu no longer exists."
    else:
        text = await cog.apply(member, category, chosen)
    await interaction.followup.send(text, ephemeral=True, allowed_mentions=NO_PINGS)


class SelfRoles(commands.Cog):
    """Let members pick their own roles from dropdown menus."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=2026093001, force_registration=True)
        self.config.register_guild(next_id=1, categories={})
        self._lock = asyncio.Lock()  # ponytail: one lock for every guild; menus change rarely

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(PickSelect, ClearButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(PickSelect, ClearButton)

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """This cog stores no user data."""
        return

    # --- reading --------------------------------------------------------------------------------

    async def categories(self, guild: discord.Guild) -> dict[int, dict[str, Any]]:
        """Every category by ID, oldest first."""
        raw = await self.config.guild(guild).categories()
        found = {}
        for key, value in raw.items() if isinstance(raw, dict) else ():
            category = clean_category(value)
            if str(key).isdigit() and category is not None:
                found[int(key)] = category
        return dict(sorted(found.items()))

    async def find(self, guild: discord.Guild, name: str) -> int:
        """A category's ID by its name, ignoring case; LookupError if there's none."""
        wanted = name.strip().casefold()
        for category_id, category in (await self.categories(guild)).items():
            if category["name"].casefold() == wanted:
                return category_id
        raise LookupError(f"There is no category called {name}.")

    async def overview(self, guild: discord.Guild, editor: discord.Member) -> list[dict[str, Any]]:
        """Every category for the dashboard: its roles, why any of them isn't handed out, and the roles the editor
        could add (not on any menu yet), highest first."""
        shown = []
        categories = await self.categories(guild)
        taken = {entry["id"] for category in categories.values() for entry in category["roles"]}
        for category_id, category in categories.items():
            roles = []
            for entry in category["roles"]:
                role = guild.get_role(entry["id"])
                problem = role_problem(guild, role) if role else "This role was deleted."
                roles.append({**entry, "name": role.name if role else "", "problem": problem})
            channel = guild.get_channel_or_thread(category["channel_id"] or 0)
            posted = channel is not None and category["message_id"] is not None
            shown.append(
                {
                    "id": category_id,
                    "name": category["name"],
                    "limit": limit_text(category["max"]),
                    "roles": roles,
                    "full": len(roles) >= MAX_OPTIONS,
                    "channel": f"#{channel.name}" if posted and channel else "",
                    "url": f"https://discord.com/channels/{guild.id}/{category['channel_id']}/{category['message_id']}"
                    if posted
                    else "",
                    "choices": [
                        {"id": role.id, "name": role.name}
                        for role in reversed(guild.roles)
                        if role.id not in taken
                        and role_problem(guild, role) is None
                        and editor_problem(editor, role) is None
                    ],
                }
            )
        return shown

    def banner_path(self, guild: discord.Guild, category_id: int, ext: str) -> Path:
        return cog_data_path(self) / "banners" / str(guild.id) / f"{category_id}.{ext}"

    # --- the posted message ---------------------------------------------------------------------

    async def render(
        self, guild: discord.Guild, category_id: int, category: dict[str, Any]
    ) -> tuple[ui.LayoutView, list[discord.File]]:
        """The category's message and its banner file."""
        view = ui.LayoutView(timeout=None)
        files = []
        if category["banner"]:
            name = f"banner.{category['banner']}"
            try:
                data = await asyncio.to_thread(self.banner_path(guild, category_id, category["banner"]).read_bytes)
            except OSError:
                log.warning("Banner of self-role category %s in %s is missing", category_id, guild.id)
            else:
                files.append(discord.File(BytesIO(data), filename=name))
                view.add_item(ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{name}")))

        usable = []
        for entry in category["roles"]:
            role = guild.get_role(entry["id"])
            if role is not None and role_problem(guild, role) is None:
                usable.append((role, entry))
        card = ui.Container(accent_colour=ACCENT)
        card.add_item(ui.TextDisplay(f"## {category['name']}\n{limit_text(category['max'])}"))
        if usable:
            lines = []
            for role, entry in usable:
                line = f"{entry['emoji']} : {role.mention}" if entry["emoji"] else role.mention
                lines.append(f"{line}\n-# {entry['note']}" if entry["note"] else line)
            card.add_item(ui.TextDisplay("\n\n".join(lines)))
            options = [
                discord.SelectOption(
                    label=role.name[:100],
                    value=str(role.id),
                    emoji=entry["emoji"] or None,
                    description=plain_note(guild, entry["note"]) or None,
                )
                for role, entry in usable
            ]
            card.add_item(ui.ActionRow().add_item(PickSelect(category_id, options, min(category["max"], len(options)))))
            card.add_item(ui.ActionRow().add_item(ClearButton(category_id)))
        else:
            card.add_item(ui.TextDisplay("No roles yet."))
        view.add_item(card)
        return view, files

    async def _refresh(self, guild: discord.Guild, category_id: int, category: dict[str, Any]) -> None:
        """Edit the posted message to match the category. Raises NotFound or _Gone when it's gone."""
        if category["channel_id"] is None or category["message_id"] is None:
            return
        channel = guild.get_channel_or_thread(category["channel_id"])
        if not isinstance(channel, discord.abc.Messageable):
            raise _Gone
        view, files = await self.render(guild, category_id, category)
        message = channel.get_partial_message(category["message_id"])
        await message.edit(view=view, attachments=files, allowed_mentions=NO_PINGS)

    async def _change(self, guild: discord.Guild, category_id: int, change: Callable[[dict[str, Any]], None]) -> None:
        """Change a category and update its posted message. If Discord refuses the new message, nothing changes.

        LookupError for a category that doesn't exist; ValueError with a message for staff otherwise.
        """
        async with self._lock:
            group = self.config.guild(guild)
            stored = await group.categories()
            category = (await self.categories(guild)).get(category_id)
            if category is None:
                raise LookupError("That category doesn't exist anymore.")
            before = copy.deepcopy(category)
            change(category)
            stored[str(category_id)] = category
            await group.categories.set(stored)
            try:
                await self._refresh(guild, category_id, category)
            except (discord.NotFound, _Gone):
                category["channel_id"] = category["message_id"] = None  # deleted: post it again
                await group.categories.set(stored)
            except Exception as exc:
                stored[str(category_id)] = before
                await group.categories.set(stored)
                if not isinstance(exc, discord.HTTPException):
                    raise
                log.warning("Discord refused self-role menu %s in %s", category_id, guild.id, exc_info=True)
                raise ValueError(
                    f"Discord refused the updated menu, so nothing was changed ({exc.text or exc.status})."
                ) from exc

    # --- changes, shared with the dashboard -----------------------------------------------------

    async def create(self, guild: discord.Guild, name: str, max_picks: int) -> int:
        name = " ".join(name.split())
        if not name or len(name) > MAX_NAME:
            raise ValueError(f"A category name needs 1 to {MAX_NAME} characters.")
        if not 1 <= max_picks <= MAX_OPTIONS:
            raise ValueError(f"The pick limit must be between 1 and {MAX_OPTIONS}.")
        async with self._lock:
            if any(c["name"].casefold() == name.casefold() for c in (await self.categories(guild)).values()):
                raise ValueError(f"There is already a category called {name}.")
            group = self.config.guild(guild)
            category_id = await group.next_id()
            await group.next_id.set(category_id + 1)
            async with group.categories() as stored:
                stored[str(category_id)] = clean_category({"name": name, "max": max_picks})
        return category_id

    async def delete(self, guild: discord.Guild, category_id: int) -> None:
        """Forget the category and delete its posted message and banner. Members keep their roles."""
        async with self._lock:
            async with self.config.guild(guild).categories() as stored:
                category = clean_category(stored.pop(str(category_id), None))
        if category is None:
            raise LookupError("That category doesn't exist anymore.")
        await _delete_message(guild, category["channel_id"], category["message_id"])
        if category["banner"]:
            await asyncio.to_thread(self.banner_path(guild, category_id, category["banner"]).unlink, True)

    async def add_role(
        self,
        guild: discord.Guild,
        editor: discord.Member,
        category_id: int,
        role: discord.Role,
        emoji: str,
        note: str = "",
    ) -> None:
        if problem := role_problem(guild, role) or editor_problem(editor, role):
            raise ValueError(problem)
        emoji, note = self.clean_emoji(guild, emoji), clean_note(note)
        # One menu per role: Clear on one menu would otherwise take away a role picked on another.
        for other in (await self.categories(guild)).values():
            if any(entry["id"] == role.id for entry in other["roles"]):
                raise ValueError(f"{role.name} is already in {other['name']}.")

        def change(category: dict[str, Any]) -> None:
            if len(category["roles"]) >= MAX_OPTIONS:
                raise ValueError(f"A menu holds at most {MAX_OPTIONS} roles.")
            category["roles"].append({"id": role.id, "emoji": emoji, "note": note})

        await self._change(guild, category_id, change)

    async def edit_role(
        self, guild: discord.Guild, category_id: int, role_id: int, *, emoji: str | None = None, note: str | None = None
    ) -> None:
        """Change a role's emoji or note in place, keeping its spot on the menu. None leaves it as it is; "" clears it."""
        changes = {}
        if emoji is not None:
            changes["emoji"] = self.clean_emoji(guild, emoji)
        if note is not None:
            changes["note"] = clean_note(note)

        def change(category: dict[str, Any]) -> None:
            entry = next((entry for entry in category["roles"] if entry["id"] == role_id), None)
            if entry is None:
                raise ValueError(f"That role isn't in {category['name']}.")
            entry.update(changes)

        await self._change(guild, category_id, change)

    async def remove_role(self, guild: discord.Guild, category_id: int, role_id: int) -> None:
        """Take a role off the menu, including one that was deleted. Members keep it."""

        def change(category: dict[str, Any]) -> None:
            if not any(entry["id"] == role_id for entry in category["roles"]):
                raise ValueError(f"That role isn't in {category['name']}.")
            category["roles"] = [entry for entry in category["roles"] if entry["id"] != role_id]

        await self._change(guild, category_id, change)

    async def set_limit(self, guild: discord.Guild, category_id: int, max_picks: int) -> None:
        if not 1 <= max_picks <= MAX_OPTIONS:
            raise ValueError(f"The pick limit must be between 1 and {MAX_OPTIONS}.")
        await self._change(guild, category_id, lambda category: category.update(max=max_picks))

    async def set_banner(self, guild: discord.Guild, category_id: int, data: bytes | None) -> None:
        """Store a new banner (PNG, JPEG, GIF or WebP), or remove it with None."""
        ext = None
        if data is not None:
            if len(data) > BANNER_MAX_BYTES:
                raise ValueError(f"A banner can be at most {BANNER_MAX_BYTES // 1024 // 1024} MB.")
            if (ext := banner_type(data)) is None:
                raise ValueError("A banner must be a PNG, JPEG, GIF or WebP image.")
            path = self.banner_path(guild, category_id, ext)
            await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, data)
        await self._change(guild, category_id, lambda category: category.update(banner=ext))
        for other in BANNER_EXTS - {ext}:  # the banner this one replaced, if it had another type
            await asyncio.to_thread(self.banner_path(guild, category_id, other).unlink, True)

    async def post(self, guild: discord.Guild, category_id: int, channel: discord.abc.Messageable) -> discord.Message:
        """Post the category's menu, replacing the one posted before."""
        async with self._lock:
            group = self.config.guild(guild)
            stored = await group.categories()
            category = (await self.categories(guild)).get(category_id)
            if category is None:
                raise LookupError("That category doesn't exist anymore.")
            if not any(
                (role := guild.get_role(entry["id"])) and role_problem(guild, role) is None
                for entry in category["roles"]
            ):
                raise ValueError(f"Add a role to {category['name']} before posting it.")
            view, files = await self.render(guild, category_id, category)
            try:
                message = await channel.send(view=view, files=files, allowed_mentions=NO_PINGS)
            except discord.Forbidden as exc:
                raise ValueError(f"I can't post there ({exc.text or exc.status}).") from exc
            except discord.HTTPException as exc:
                raise ValueError(f"Discord refused the menu ({exc.text or exc.status}).") from exc
            old = (category["channel_id"], category["message_id"])
            category["channel_id"], category["message_id"] = message.channel.id, message.id
            stored[str(category_id)] = category
            await group.categories.set(stored)
        if old != (category["channel_id"], category["message_id"]):
            await _delete_message(guild, *old)
        return message

    def clean_emoji(self, guild: discord.Guild, text: str) -> str:
        """The emoji as stored: "" for none, a custom emoji the bot can use, or a Unicode emoji. `:name:` finds a
        custom emoji of the server by name, for the dashboard, where the <:name:id> form is hard to type."""
        text = text.strip()
        if not text:
            return ""
        if match := EMOJI_NAME.fullmatch(text):
            emoji = discord.utils.get(guild.emojis, name=match[1])
            if emoji is None:
                raise ValueError(f"This server has no emoji called {text}.")
            return str(emoji)
        if match := CUSTOM_EMOJI.fullmatch(text):
            if self.bot.get_emoji(int(match[1])) is None:
                raise ValueError("I can't use that emoji. Pick one from this server, or a normal emoji.")
            return text
        if is_unicode_emoji(text):
            return text
        raise ValueError("That isn't an emoji. Use one emoji, like ❤️ or one from this server.")

    # --- keeping posted menus current -----------------------------------------------------------

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        """A menu shows role names and leaves out roles it may not hand out, so it follows renames and changes that
        make a role (un)fit to hand out. A reorder that changes neither leaves the menus alone."""
        guild = after.guild
        if before.name == after.name and (role_problem(guild, before) is None) == (role_problem(guild, after) is None):
            return
        await self._refresh_menus_with(after)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self._refresh_menus_with(role)

    async def _refresh_menus_with(self, role: discord.Role) -> None:
        guild = role.guild
        if await self.bot.cog_disabled_in_guild(self, guild):
            return
        for category_id, category in (await self.categories(guild)).items():
            if category["message_id"] and any(entry["id"] == role.id for entry in category["roles"]):
                try:
                    await self._change(guild, category_id, lambda _: None)
                except (LookupError, ValueError):
                    log.warning("Could not update self-role menu %s in %s", category_id, guild.id, exc_info=True)

    # --- picking --------------------------------------------------------------------------------

    async def apply(self, member: discord.Member, category: dict[str, Any], chosen: list[int]) -> str:
        """Give the member exactly the chosen roles of the category; returns the reply for them."""
        guild = member.guild
        usable = {}
        for entry in category["roles"]:
            role = guild.get_role(entry["id"])
            if role is not None and role_problem(guild, role) is None:
                usable[role.id] = role
        wanted = [usable[role_id] for role_id in dict.fromkeys(chosen) if role_id in usable][: category["max"]]
        add = [role for role in wanted if role not in member.roles]
        remove = [role for role in member.roles if role.id in usable and role not in wanted]
        if not guild.me.guild_permissions.manage_roles:
            return "I can't change roles right now. Please tell a moderator."
        reason = f"Self roles: {category['name']}"
        try:
            if remove:
                await member.remove_roles(*remove, reason=reason)
            if add:
                await member.add_roles(*add, reason=reason)
        except discord.Forbidden:
            return "I couldn't change your roles. Please tell a moderator."
        except discord.HTTPException:
            log.warning("Could not set self roles for %s in %s", member.id, guild.id, exc_info=True)
            return "Discord didn't take the change. Please try again."
        if wanted:
            return f"Your {category['name']}: {humanize_list([role.mention for role in wanted])}."
        return f"Removed your {category['name']} roles." if remove else f"You have no {category['name']} roles."

    # --- commands -------------------------------------------------------------------------------

    async def _find_or_say(self, ctx: commands.Context, name: str) -> int | None:
        assert ctx.guild is not None
        try:
            return await self.find(ctx.guild, name)
        except LookupError as exc:
            await ctx.send(str(exc))
            return None

    async def _run(self, ctx: commands.Context, done: str, action: Any) -> None:
        """Run a change and report it, or report why it was refused."""
        try:
            await action
        except (LookupError, ValueError) as exc:
            await ctx.send(str(exc), allowed_mentions=NO_PINGS)
            return
        await ctx.send(done, allowed_mentions=NO_PINGS)

    @commands.group()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.mod_or_permissions(manage_roles=True)
    async def selfroles(self, ctx: commands.Context) -> None:
        """Dropdown menus where members pick their own roles."""

    @selfroles.command(name="list")
    async def selfroles_list(self, ctx: commands.Context) -> None:
        """Show every category, its roles and where it's posted."""
        assert ctx.guild is not None
        categories = await self.categories(ctx.guild)
        if not categories:
            await ctx.send("No categories yet. Create one with `selfroles create`.")
            return
        lines = []
        for category in categories.values():
            channel = ctx.guild.get_channel_or_thread(category["channel_id"] or 0)
            where = f"posted in #{channel.name}" if channel and category["message_id"] else "not posted"
            names = [
                (
                    f"{entry['emoji']} {role.name}".strip()
                    if (role := ctx.guild.get_role(entry["id"]))
                    else "(deleted role)"
                )
                + (f" ({entry['note']})" if entry["note"] else "")
                for entry in category["roles"]
            ]
            lines.append(
                f"**{category['name']}** ({limit_text(category['max'])[:-1].lower()}, {where}): "
                + (", ".join(names) or "no roles")
            )
        for page in pagify("\n".join(lines)):
            await ctx.send(page, allowed_mentions=NO_PINGS)

    @selfroles.command(name="create")
    @commands.admin_or_permissions(manage_guild=True)
    async def selfroles_create(self, ctx: commands.Context, max_picks: int, *, name: str) -> None:
        """Create a category where members may pick up to `max_picks` roles."""
        assert ctx.guild is not None
        await self._run(
            ctx,
            f"Created {name}. Add roles with `selfroles addrole` or on the dashboard, then `selfroles post` it.",
            self.create(ctx.guild, name, max_picks),
        )

    @selfroles.command(name="delete")
    @commands.admin_or_permissions(manage_guild=True)
    async def selfroles_delete(self, ctx: commands.Context, *, name: str) -> None:
        """Delete a category and its posted menu. Members keep their roles."""
        assert ctx.guild is not None
        if (category_id := await self._find_or_say(ctx, name)) is not None:
            await self._run(ctx, f"Deleted {name}.", self.delete(ctx.guild, category_id))

    @selfroles.command(name="limit")
    @commands.admin_or_permissions(manage_guild=True)
    async def selfroles_limit(self, ctx: commands.Context, max_picks: int, *, name: str) -> None:
        """Change how many roles members may pick in a category."""
        assert ctx.guild is not None
        if (category_id := await self._find_or_say(ctx, name)) is not None:
            await self._run(ctx, f"{name}: {limit_text(max_picks)}", self.set_limit(ctx.guild, category_id, max_picks))

    @selfroles.command(name="banner")
    @commands.admin_or_permissions(manage_guild=True)
    async def selfroles_banner(self, ctx: commands.Context, *, name: str) -> None:
        """Set a category's banner from an attached image, or remove it when nothing is attached."""
        assert ctx.guild is not None
        if (category_id := await self._find_or_say(ctx, name)) is None:
            return
        attachment = ctx.message.attachments[0] if ctx.message.attachments else None
        if attachment is not None and attachment.size > BANNER_MAX_BYTES:
            await ctx.send(f"A banner can be at most {BANNER_MAX_BYTES // 1024 // 1024} MB.")
            return
        data = await attachment.read() if attachment is not None else None
        done = f"Set the banner of {name}." if data is not None else f"Removed the banner of {name}."
        await self._run(ctx, done, self.set_banner(ctx.guild, category_id, data))

    @selfroles.command(name="post")
    @commands.admin_or_permissions(manage_guild=True)
    async def selfroles_post(
        self, ctx: commands.Context, name: str, channel: discord.TextChannel | discord.Thread | None = None
    ) -> None:
        """Post a category's menu (put the name in quotes if it has spaces). Replaces the one posted before."""
        assert ctx.guild is not None
        if (category_id := await self._find_or_say(ctx, name)) is None:
            return
        target = channel or ctx.channel
        try:
            message = await self.post(ctx.guild, category_id, target)
        except (LookupError, ValueError) as exc:
            await ctx.send(str(exc), allowed_mentions=NO_PINGS)
            return
        if target != ctx.channel:
            await ctx.send(f"Posted: {message.jump_url}")

    @selfroles.command(name="addrole")
    async def selfroles_addrole(self, ctx: commands.Context, name: str, role: discord.Role, emoji: str = "") -> None:
        """Add a role to a category (put the name in quotes if it has spaces)."""
        assert ctx.guild is not None and isinstance(ctx.author, discord.Member)
        if (category_id := await self._find_or_say(ctx, name)) is not None:
            await self._run(
                ctx, f"Added {role.name} to {name}.", self.add_role(ctx.guild, ctx.author, category_id, role, emoji)
            )

    @selfroles.command(name="note")
    async def selfroles_note(self, ctx: commands.Context, name: str, role: discord.Role, *, note: str = "") -> None:
        """Set the note shown under a role on a menu, or clear it with no note (put the name in quotes if it has
        spaces). Up to 100 characters; a #channel mention shows as a link in the list."""
        assert ctx.guild is not None
        if (category_id := await self._find_or_say(ctx, name)) is not None:
            done = f"Set the note for {role.name}." if note.strip() else f"Cleared the note for {role.name}."
            await self._run(ctx, done, self.edit_role(ctx.guild, category_id, role.id, note=note))

    @selfroles.command(name="emoji")
    async def selfroles_emoji(self, ctx: commands.Context, name: str, role: discord.Role, emoji: str = "") -> None:
        """Change a role's emoji on a menu, or clear it with no emoji (put the name in quotes if it has spaces)."""
        assert ctx.guild is not None
        if (category_id := await self._find_or_say(ctx, name)) is not None:
            done = f"Set the emoji for {role.name}." if emoji.strip() else f"Cleared the emoji for {role.name}."
            await self._run(ctx, done, self.edit_role(ctx.guild, category_id, role.id, emoji=emoji))

    @selfroles.command(name="removerole")
    async def selfroles_removerole(self, ctx: commands.Context, name: str, role: discord.Role) -> None:
        """Take a role off a category (put the name in quotes if it has spaces). Members keep it."""
        assert ctx.guild is not None
        if (category_id := await self._find_or_say(ctx, name)) is not None:
            await self._run(ctx, f"Removed {role.name} from {name}.", self.remove_role(ctx.guild, category_id, role.id))


async def _delete_message(guild: discord.Guild, channel_id: int | None, message_id: int | None) -> None:
    """Delete a posted menu if it's still there."""
    channel = guild.get_channel_or_thread(channel_id or 0)
    if isinstance(channel, discord.abc.Messageable) and message_id:
        with contextlib.suppress(discord.HTTPException):
            await channel.get_partial_message(message_id).delete()
