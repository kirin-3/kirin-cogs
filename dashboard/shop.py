"""The staff site's role shop page: the shop posted in the shop channel, its sections, and the shop's items.

The rules live in the Unicornia cog (unicornia/shop_channel.py, reached with bot.get_cog, never imported): who may
change the shop (the same gate as [p]shop add), which roles may be sold, the limits, and updating the posted messages.
It raises LookupError for a section or item that doesn't exist and ValueError with a message for staff; this module
only turns those into pages. Every staff member can see the page; a change by anyone else gets 403.
"""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import discord
from aiohttp import web

if TYPE_CHECKING:
    from .dashboard import Dashboard

MAX_NAME = 200  # the cog refuses more than 100; this only bounds what is read
MAX_NOTE = 2000
MAX_PRICE_DIGITS = 13
STEPS = {"up": -1, "down": 1}


def _field(form: Any, name: str, limit: int) -> str:
    value = form.get(name, "")
    return value[:limit] if isinstance(value, str) else ""


def _digits(form: Any, name: str, limit: int = 20) -> int | None:
    """A whole number of up to `limit` ASCII digits, or None."""
    raw = _field(form, name, limit + 1).strip()
    return int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= limit else None


class StaffShop:
    def __init__(self, cog: "Dashboard") -> None:
        self.cog = cog

    def add_routes(self, app: web.Application) -> None:
        section, item = r"{section_id:\d{1,9}}", r"{item_id:\d{1,18}}"
        app.router.add_get("/shop", self.page)
        app.router.add_post("/shop/post", self.post)
        app.router.add_post("/shop/sections", self.section_create)
        app.router.add_post(f"/shop/sections/{section}", self.section_edit)
        app.router.add_post(f"/shop/sections/{section}/banner", self.section_banner)
        app.router.add_post(f"/shop/sections/{section}/delete", self.section_delete)
        app.router.add_post(f"/shop/sections/{section}/move", self.section_move)
        app.router.add_post(f"/shop/sections/{section}/items/{item}/move", self.item_move)
        app.router.add_post("/shop/items", self.item_add)
        app.router.add_post(f"/shop/items/{item}", self.item_edit)
        app.router.add_post(f"/shop/items/{item}/delete", self.item_delete)

    def _shop(self, request: web.Request) -> tuple[discord.Guild, discord.Member, Any]:
        uni = self.cog.bot.get_cog("Unicornia")
        guild = self.cog.guild()
        editor = self.cog.member(request["session"].user_id)
        if uni is None or guild is None or editor is None:
            page = self.cog._message(
                request, 503, "Not available", "Unicornia isn't loaded right now. Try again later."
            )
            raise web.HTTPServiceUnavailable(text=page.text, content_type="text/html")
        return guild, editor, uni

    async def page(
        self, request: web.Request, *, error: str = "", error_for: str = "", status: int = 200
    ) -> web.StreamResponse:
        guild, editor, uni = self._shop(request)
        shop = await uni.shop_overview(guild, editor)
        return self.cog._render(request, "shop.html", status=status, shop=shop, error=error, error_for=error_for)

    async def _change(
        self, request: web.Request, anchor: str, change: Callable[[], Awaitable[Any]]
    ) -> web.StreamResponse:
        """Run the change and go back to its place on the page, or show the page again with why it was refused."""
        _guild, editor, uni = self._shop(request)
        if not await uni.shop_may_manage(editor):
            return self.cog._message(
                request, 403, "Not allowed", "Changing the shop needs Manage Roles or the bot's admin role."
            )
        try:
            await change()
        except LookupError as exc:
            return self.cog._message(request, 404, "Not found", str(exc))
        except ValueError as exc:
            return await self.page(request, error=str(exc), error_for=anchor, status=400)
        raise web.HTTPFound(f"/shop#{anchor}")

    def _role(self, guild: discord.Guild, form: Any, name: str) -> discord.Role | None:
        role_id = _digits(form, name)
        return guild.get_role(role_id) if role_id else None

    async def post(self, request: web.Request) -> web.StreamResponse:
        guild, _editor, uni = self._shop(request)
        form = await request.post()
        channel = guild.get_channel(_digits(form, "channel") or 0)
        if not isinstance(channel, discord.TextChannel):
            return await self.page(request, error="Choose a channel to post in.", error_for="channel", status=400)
        return await self._change(request, "channel", lambda: uni.shop_post(guild, channel))

    async def section_create(self, request: web.Request) -> web.StreamResponse:
        guild, _editor, uni = self._shop(request)
        form = await request.post()
        name, note = _field(form, "name", MAX_NAME), _field(form, "note", MAX_NOTE)
        return await self._change(request, "new-section", lambda: uni.shop_section_create(guild, name, note))

    async def section_edit(self, request: web.Request) -> web.StreamResponse:
        guild, _editor, uni = self._shop(request)
        form = await request.post()
        section_id = int(request.match_info["section_id"])
        name, note = _field(form, "name", MAX_NAME), _field(form, "note", MAX_NOTE)
        return await self._change(
            request, f"section-{section_id}", lambda: uni.shop_section_edit(guild, section_id, name, note)
        )

    async def section_banner(self, request: web.Request) -> web.StreamResponse:
        guild, _editor, uni = self._shop(request)
        form = await request.post()
        section_id = int(request.match_info["section_id"])
        upload = form.get("banner")
        if form.get("remove"):
            data = None
        elif isinstance(upload, web.FileField):
            data = upload.file.read()
        else:
            error = "Choose an image to upload."
            return await self.page(request, error=error, error_for=f"section-{section_id}", status=400)
        return await self._change(
            request, f"section-{section_id}", lambda: uni.shop_section_banner(guild, section_id, data)
        )

    async def section_delete(self, request: web.Request) -> web.StreamResponse:
        guild, _editor, uni = self._shop(request)
        section_id = int(request.match_info["section_id"])
        return await self._change(request, "new-section", lambda: uni.shop_section_delete(guild, section_id))

    async def _step(self, request: web.Request, anchor: str) -> int | web.StreamResponse:
        step = STEPS.get(_field(await request.post(), "direction", 4))
        if step is None:
            return await self.page(request, error="Choose up or down.", error_for=anchor, status=400)
        return step

    async def section_move(self, request: web.Request) -> web.StreamResponse:
        guild, _editor, uni = self._shop(request)
        section_id = int(request.match_info["section_id"])
        step = await self._step(request, f"section-{section_id}")
        if not isinstance(step, int):
            return step
        return await self._change(
            request, f"section-{section_id}", lambda: uni.shop_section_move(guild, section_id, step)
        )

    async def item_move(self, request: web.Request) -> web.StreamResponse:
        guild, _editor, uni = self._shop(request)
        section_id, item_id = int(request.match_info["section_id"]), int(request.match_info["item_id"])
        step = await self._step(request, f"section-{section_id}")
        if not isinstance(step, int):
            return step
        return await self._change(
            request, f"section-{section_id}", lambda: uni.shop_item_move(guild, section_id, item_id, step)
        )

    def _item_form(self, guild: discord.Guild, form: Any) -> tuple[str, int | None, Any, Any, int | None]:
        return (
            _field(form, "name", MAX_NAME),
            _digits(form, "price", MAX_PRICE_DIGITS),
            self._role(guild, form, "role"),
            self._role(guild, form, "requirement"),
            _digits(form, "section", 9),
        )

    async def item_add(self, request: web.Request) -> web.StreamResponse:
        guild, editor, uni = self._shop(request)
        name, price, role, requirement, section_id = self._item_form(guild, await request.post())
        if role is None or price is None:
            error = "Choose a role and a price of 0 or more."
            return await self.page(request, error=error, error_for="items", status=400)
        return await self._change(
            request, "items", lambda: uni.shop_item_add(guild, editor, name, price, role, requirement, section_id)
        )

    async def item_edit(self, request: web.Request) -> web.StreamResponse:
        guild, editor, uni = self._shop(request)
        item_id = int(request.match_info["item_id"])
        name, price, role, requirement, section_id = self._item_form(guild, await request.post())
        if price is None:
            return await self.page(request, error="The price must be 0 or more.", error_for="items", status=400)
        return await self._change(
            request,
            "items",
            lambda: uni.shop_item_edit(guild, editor, item_id, name, price, role, requirement, section_id),
        )

    async def item_delete(self, request: web.Request) -> web.StreamResponse:
        guild, _editor, uni = self._shop(request)
        item_id = int(request.match_info["item_id"])
        return await self._change(request, "items", lambda: uni.shop_item_delete(guild, item_id))
