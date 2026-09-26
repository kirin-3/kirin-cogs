"""The member site's pages, my.unicornia.net: roleplay settings for everyone, and self-service for supporters.

Every rule lives in the cogs themselves (reached with bot.get_cog, never imported), so the site and the bot's commands
can't drift apart. Their methods raise ValueError with a message for the member; the pages show it.
"""

import asyncio
from typing import TYPE_CHECKING, Any, NoReturn

import discord
from aiohttp import web

if TYPE_CHECKING:
    from .dashboard import Dashboard

ACTIVE_SUPPORTER = 700121551483437128
INACTIVE_SUPPORTER = 1458440559713718466
SUPPORTER_ROLES = frozenset({ACTIVE_SUPPORTER, INACTIVE_SUPPORTER})
TOGGLE_STATES = {"on": True, "off": False}


async def _upload(form: Any, name: str) -> tuple[str, bytes] | None:
    """(filename, data) of an uploaded file, or None when the file field was left empty."""
    field = form.get(name)
    if not isinstance(field, web.FileField) or not field.filename:
        return None
    data = await asyncio.to_thread(field.file.read)
    return (field.filename, data) if data else None


def _text(form: Any, name: str) -> str:
    value = form.get(name, "")
    return value.strip() if isinstance(value, str) else ""


class MemberSite:
    def __init__(self, cog: "Dashboard") -> None:
        self.cog = cog

    def add_routes(self, app: web.Application) -> None:
        emoji = r"{emoji_id:\d{1,20}}"
        app.router.add_get("/", self.home)
        app.router.add_get("/roleplay", self.roleplay)
        app.router.add_post("/roleplay", self.roleplay_toggle)
        app.router.add_get("/commands", self.commands)
        app.router.add_post("/commands", self.command_create)
        app.router.add_post("/commands/edit", self.command_edit)
        app.router.add_post("/commands/delete", self.command_delete)
        app.router.add_get("/emojis", self.emojis)
        app.router.add_post("/emojis", self.emoji_create)
        app.router.add_post(f"/emojis/{emoji}/rename", self.emoji_rename)
        app.router.add_post(f"/emojis/{emoji}/delete", self.emoji_delete)
        app.router.add_get("/role", self.role)
        app.router.add_post("/role/color", self.role_color)
        app.router.add_post("/role/holographic", self.role_holographic)
        app.router.add_post("/role/name", self.role_name)
        app.router.add_post("/role/icon", self.role_icon)
        app.router.add_post("/role/mentionable", self.role_mentionable)

    async def sections(self, member: discord.Member) -> dict[str, bool]:
        """Which sections the member sees, from their roles right now."""
        supporter = any(role.id in SUPPORTER_ROLES for role in member.roles)
        crc = self.cog.bot.get_cog("CustomRoleColor")
        has_role = supporter and crc is not None and await crc.assigned_role(member) is not None  # type: ignore[attr-defined]
        return {"supporter": supporter, "role": has_role}

    # --- helpers ---------------------------------------------------------------------------------

    def _render(self, request: web.Request, template: str, *, status: int = 200, **context: Any) -> web.Response:
        return self.cog._render(request, f"member/{template}", status=status, **context)

    def _refuse(self, request: web.Request, status: int, title: str, text: str) -> NoReturn:
        page = self.cog._message(request, status, title, text)
        error = {403: web.HTTPForbidden, 404: web.HTTPNotFound, 503: web.HTTPServiceUnavailable}[status]
        raise error(text=page.text, content_type="text/html")

    def _require(self, request: web.Request, section: str) -> discord.Member:
        if not request["nav"][section]:
            if section == "supporter":
                self._refuse(request, 403, "Supporters only", "This page is for Unicornia supporters.")
            self._refuse(request, 403, "No custom role", "You don't have a custom role to manage.")
        return request["member"]

    def _cog(self, name: str) -> Any:
        return self.cog.bot.get_cog(name)

    def _missing(self, request: web.Request, what: str) -> NoReturn:
        self._refuse(request, 503, "Not available", f"{what} are not available right now. Try again later.")

    # --- home and roleplay -----------------------------------------------------------------------

    async def home(self, request: web.Request) -> web.StreamResponse:
        return self._render(request, "home.html", member=request["member"])

    async def roleplay(self, request: web.Request, *, error: str = "", status: int = 200) -> web.StreamResponse:
        rp = self._cog("Roleplay")
        if rp is None:
            return self._render(request, "roleplay.html", missing=True)
        settings = await rp.settings_for(request["member"].id)
        toggles, lists = [], []
        for key, item in settings.items():
            value = item["value"]
            if isinstance(value, bool):
                toggles.append({"key": key, **item})
            else:
                ids = value if isinstance(value, list) else []
                lists.append({"key": key, **item, "names": [self._name(user_id) for user_id in ids]})
        return self._render(request, "roleplay.html", status=status, toggles=toggles, lists=lists, error=error)

    def _name(self, user_id: object) -> str:
        if not isinstance(user_id, int):
            return "Unknown user"
        member = self.cog.member(user_id)
        if member is not None:
            return member.display_name
        user = self.cog.bot.get_user(user_id)
        return user.name if user else "Unknown user"

    async def roleplay_toggle(self, request: web.Request) -> web.StreamResponse:
        rp = self._cog("Roleplay")
        if rp is None:
            self._missing(request, "Roleplay settings")
        form = await request.post()
        state = TOGGLE_STATES.get(_text(form, "value"))
        if state is None:
            raise web.HTTPBadRequest()
        try:
            await rp.set_toggle(request["member"].id, _text(form, "key"), state)
        except ValueError:
            raise web.HTTPBadRequest() from None
        raise web.HTTPFound("/roleplay")

    # --- custom commands -------------------------------------------------------------------------

    async def commands(self, request: web.Request, *, error: str = "", status: int = 200, **draft: str) -> web.Response:
        member = self._require(request, "supporter")
        cc = self._cog("CustomCommand")
        if cc is None:
            return self._render(request, "commands.html", missing=True)
        return self._render(
            request,
            "commands.html",
            status=status,
            commands=await cc.commands_for(member),
            limit=await cc.limit_for(member),
            can_create=cc.can_create(member),
            error=error,
            draft=draft,
        )

    async def command_create(self, request: web.Request) -> web.StreamResponse:
        member = self._require(request, "supporter")
        cc = self._cog("CustomCommand")
        if cc is None:
            self._missing(request, "Custom commands")
        if not cc.can_create(member):
            self._refuse(request, 403, "Active supporters only", "Only active supporters can create commands.")
        form = await request.post()
        trigger, response = _text(form, "trigger"), _text(form, "response")
        try:
            await cc.create_command(member, trigger, response, await _upload(form, "file"), source="web")
        except ValueError as e:
            return await self.commands(request, error=str(e), status=400, trigger=trigger, response=response)
        raise web.HTTPFound("/commands")

    async def command_edit(self, request: web.Request) -> web.StreamResponse:
        member = self._require(request, "supporter")
        cc = self._cog("CustomCommand")
        if cc is None:
            self._missing(request, "Custom commands")
        if not cc.can_create(member):
            self._refuse(request, 403, "Active supporters only", "Only active supporters can edit commands.")
        form = await request.post()
        old = _text(form, "old")
        try:
            await cc.edit_command(
                member,
                old,
                _text(form, "trigger") or old,
                _text(form, "response"),
                await _upload(form, "file"),
                remove_file=bool(form.get("remove_file")),
                source="web",
            )
        except ValueError as e:
            return await self.commands(request, error=str(e), status=400)
        raise web.HTTPFound("/commands")

    async def command_delete(self, request: web.Request) -> web.StreamResponse:
        member = self._require(request, "supporter")
        cc = self._cog("CustomCommand")
        if cc is None:
            self._missing(request, "Custom commands")
        try:
            await cc.delete_command(member, _text(await request.post(), "trigger"), source="web")
        except ValueError as e:
            return await self.commands(request, error=str(e), status=400)
        raise web.HTTPFound("/commands")

    # --- custom emojis ---------------------------------------------------------------------------

    async def emojis(self, request: web.Request, *, error: str = "", status: int = 200) -> web.Response:
        member = self._require(request, "supporter")
        ce = self._cog("CustomEmoji")
        if ce is None:
            return self._render(request, "emojis.html", missing=True)
        used, limit = await ce.slots_for(member)
        return self._render(
            request,
            "emojis.html",
            status=status,
            emojis=await ce.emojis_for(member),
            used=used,
            limit=limit,
            can_create=await ce.can_create(member),
            error=error,
        )

    async def _emoji_cog(self, request: web.Request, *, needs_role: bool) -> tuple[discord.Member, Any]:
        member = self._require(request, "supporter")
        ce = self._cog("CustomEmoji")
        if ce is None:
            self._missing(request, "Custom emojis")
        if needs_role and not await ce.can_create(member):
            self._refuse(request, 403, "Active supporters only", "Only active supporters can create or rename emojis.")
        return member, ce

    def _emoji(self, request: web.Request, member: discord.Member) -> discord.Emoji:
        emoji = member.guild.get_emoji(int(request.match_info["emoji_id"]))
        if emoji is None:
            self._refuse(request, 404, "Emoji not found", "That emoji no longer exists.")
        return emoji

    async def emoji_create(self, request: web.Request) -> web.StreamResponse:
        member, ce = await self._emoji_cog(request, needs_role=True)
        form = await request.post()
        upload = await _upload(form, "image")
        try:
            if upload is None:
                raise ValueError("Choose a PNG, JPEG or GIF image to upload.")
            await ce.create_emoji(member, _text(form, "name"), upload[1])
        except ValueError as e:
            return await self.emojis(request, error=str(e), status=400)
        raise web.HTTPFound("/emojis")

    async def emoji_rename(self, request: web.Request) -> web.StreamResponse:
        member, ce = await self._emoji_cog(request, needs_role=True)
        emoji = self._emoji(request, member)
        try:
            await ce.rename_emoji(member, emoji, _text(await request.post(), "name"))
        except ValueError as e:
            return await self.emojis(request, error=str(e), status=400)
        raise web.HTTPFound("/emojis")

    async def emoji_delete(self, request: web.Request) -> web.StreamResponse:
        member, ce = await self._emoji_cog(request, needs_role=False)
        emoji = self._emoji(request, member)
        try:
            await ce.delete_emoji(member, emoji)
        except ValueError as e:
            return await self.emojis(request, error=str(e), status=400)
        raise web.HTTPFound("/emojis")

    # --- custom role -----------------------------------------------------------------------------

    async def role(self, request: web.Request, *, error: str = "", status: int = 200) -> web.Response:
        member = self._require(request, "role")
        crc = self._cog("CustomRoleColor")
        # Unloaded, or the assignment went away since the navigation was worked out
        if crc is None or (role := await crc.assigned_role(member)) is None:
            self._refuse(request, 403, "No custom role", "You don't have a custom role to manage.")
        icon = role.display_icon
        return self._render(
            request,
            "role.html",
            status=status,
            role=role,
            colors=[f"{c.value:06x}" for c in (role.colour, role.secondary_colour, role.tertiary_colour) if c],
            icon_url=icon.url if isinstance(icon, discord.Asset) else None,
            icon_emoji=icon if isinstance(icon, str) else None,
            icons_allowed="ROLE_ICONS" in member.guild.features,
            problem=crc._preflight_role_edit(member.guild, role),
            error=error,
        )

    async def _role_change(self, request: web.Request, change: str, *args: Any) -> web.StreamResponse:
        member = self._require(request, "role")
        crc = self._cog("CustomRoleColor")
        if crc is None:
            self._missing(request, "Custom roles")
        try:
            await getattr(crc, change)(member, *args)
        except ValueError as e:
            return await self.role(request, error=str(e), status=400)
        raise web.HTTPFound("/role")

    async def role_color(self, request: web.Request) -> web.StreamResponse:
        form = await request.post()
        secondary = _text(form, "secondary") if form.get("gradient") else None
        return await self._role_change(request, "set_color", _text(form, "primary"), secondary)

    async def role_holographic(self, request: web.Request) -> web.StreamResponse:
        return await self._role_change(request, "set_holographic")

    async def role_name(self, request: web.Request) -> web.StreamResponse:
        return await self._role_change(request, "set_name", _text(await request.post(), "name"))

    async def role_icon(self, request: web.Request) -> web.StreamResponse:
        form = await request.post()
        upload = await _upload(form, "image")
        emoji = _text(form, "emoji") or None
        return await self._role_change(request, "set_icon", emoji, upload[1] if upload and not emoji else None)

    async def role_mentionable(self, request: web.Request) -> web.StreamResponse:
        state = TOGGLE_STATES.get(_text(await request.post(), "state"))
        if state is None:
            raise web.HTTPBadRequest()
        return await self._role_change(request, "set_mentionable", state)
