"""The staff site's self-role page: the SelfRoles cog's categories, with forms to add and remove their roles.

The rules live in the SelfRoles cog (reached with bot.get_cog, never imported): which roles may go on a menu, who may
add them, and updating the posted menu. It raises LookupError for a category that doesn't exist and ValueError with a
message for staff; this module only turns those into pages. Categories are created, posted and deleted with
[p]selfroles in Discord.
"""

from typing import TYPE_CHECKING, Any

import discord
from aiohttp import web

if TYPE_CHECKING:
    from .dashboard import Dashboard

MAX_EMOJI = 64


class StaffSelfRoles:
    def __init__(self, cog: "Dashboard") -> None:
        self.cog = cog

    def add_routes(self, app: web.Application) -> None:
        category, role = r"{category_id:\d{1,18}}", r"{role_id:\d{1,20}}"
        app.router.add_get("/selfroles", self.page)
        app.router.add_post(f"/selfroles/{category}/roles", self.add)
        app.router.add_post(f"/selfroles/{category}/roles/{role}/delete", self.remove)

    def _selfroles(self, request: web.Request) -> tuple[discord.Guild, discord.Member, Any]:
        selfroles = self.cog.bot.get_cog("SelfRoles")
        guild = self.cog.guild()
        editor = self.cog.member(request["session"].user_id)
        if selfroles is None or guild is None or editor is None:
            page = self.cog._message(
                request, 503, "Not available", "Self roles aren't loaded right now. Try again later."
            )
            raise web.HTTPServiceUnavailable(text=page.text, content_type="text/html")
        return guild, editor, selfroles

    async def page(
        self, request: web.Request, *, error: str = "", error_for: int | None = None, status: int = 200
    ) -> web.StreamResponse:
        guild, editor, selfroles = self._selfroles(request)
        categories = await selfroles.overview(guild, editor)
        return self.cog._render(
            request, "selfroles.html", status=status, categories=categories, error=error, error_for=error_for
        )

    async def _done(self, request: web.Request, change: Any) -> web.StreamResponse:
        """Run the change and go back to its category, or show the page again with why it was refused."""
        category_id = int(request.match_info["category_id"])
        try:
            await change
        except LookupError:
            return self.cog._message(
                request, 404, "Category not found", "There is no self-role category with that number."
            )
        except ValueError as exc:
            return await self.page(request, error=str(exc), error_for=category_id, status=400)
        raise web.HTTPFound(f"/selfroles#category-{category_id}")

    async def add(self, request: web.Request) -> web.StreamResponse:
        guild, editor, selfroles = self._selfroles(request)
        form = await request.post()
        raw = form.get("role")
        # Not gifs._digits: that caps at 12 digits, and a role ID has up to 20.
        role_id = int(raw) if isinstance(raw, str) and raw.isascii() and raw.isdigit() and len(raw) <= 20 else None
        role = guild.get_role(role_id) if role_id else None
        if role is None:
            error = "Choose a role to add."
            return await self.page(request, error=error, error_for=int(request.match_info["category_id"]), status=400)
        emoji = str(form.get("emoji", ""))[:MAX_EMOJI]
        return await self._done(
            request, selfroles.add_role(guild, editor, int(request.match_info["category_id"]), role, emoji)
        )

    async def remove(self, request: web.Request) -> web.StreamResponse:
        guild, _editor, selfroles = self._selfroles(request)
        category_id, role_id = int(request.match_info["category_id"]), int(request.match_info["role_id"])
        return await self._done(request, selfroles.remove_role(guild, category_id, role_id))
