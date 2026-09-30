"""The roleplay gifs on the sites: browse, vote and send in a gif on the member site, vote totals on the staff site.

The rules live in the Roleplay cog (reached with bot.get_cog, never imported): which gifs there are, who may send one
in, what is accepted. It raises LookupError for a gif or page that doesn't exist and ValueError with a message for the
member; this module only turns those into pages. A gif's name from the URL or a form is never joined onto a path: the
cog looks it up in the folder's listing.
"""

from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import quote

from aiohttp import web

from .member import _text

if TYPE_CHECKING:
    from .dashboard import Dashboard

GIF_UPLOAD_PATH = "/gifs/upload"
VOTES = {"up": 1, "down": -1, "none": 0}
POOLS = ("default", "wlw", "mlm")  # roleplay.actions.POOLS: the pool pages, and what a form may name
STAFF_PAGE = 10
MAX_PAGE = 10_000
MAX_SLOT = 50  # a page holds 5 gifs; the slot only picks the #g<slot> anchor to return to
GIF_CACHE = "private, max-age=86400"  # a gif optimized under the same name shows up within a day


def _digits(raw: object) -> int | None:
    """The number in a form or query value of plain digits; None for anything else. Long ones are capped, since Python
    refuses to convert thousands of digits."""
    if not (isinstance(raw, str) and raw.isascii() and raw.isdigit()):
        return None
    return int(raw) if len(raw) <= 12 else 10**12


def _number(raw: object, low: int, high: int) -> int | None:
    """A whole number from a form or query value, or None if it isn't one in range."""
    number = _digits(raw)
    return number if number is not None and low <= number <= high else None


def _page(raw: object) -> int:
    """A page number from a query: at least 1, and a huge one is left for the cog to clamp to the last page."""
    return min(_digits(raw) or 1, MAX_PAGE)


def page_url(action: str, pool: str, page: int) -> str:
    """The URL of a gif page, built from parts already checked, never from a URL the client sent."""
    path = f"/gifs/{quote(action, safe='')}" + ("" if pool == "default" else f"/{pool}")
    return f"{path}?page={page}"


class _Gifs:
    """The parts the member and staff sites share: reaching the cog, 503 and 404 pages, and the gif file."""

    file_headers: dict[str, str] | None = None

    def __init__(self, cog: "Dashboard") -> None:
        self.cog = cog

    def _stop(
        self, request: web.Request, error: type[web.HTTPException], status: int, title: str, text: str
    ) -> NoReturn:
        page = self.cog._message(request, status, title, text)
        raise error(text=page.text, content_type="text/html")

    def _roleplay(self, request: web.Request) -> Any:
        roleplay = self.cog.bot.get_cog("Roleplay")
        if roleplay is None:
            self._stop(
                request,
                web.HTTPServiceUnavailable,
                503,
                "Not available",
                "The gifs are not available right now. Try again later.",
            )
        return roleplay

    def _not_found(self, request: web.Request) -> NoReturn:
        self._stop(request, web.HTTPNotFound, 404, "Not found", "There is no gif or page here.")

    async def file(self, request: web.Request) -> web.StreamResponse:
        path = await self._roleplay(request).gif_path(request.match_info["action"], request.match_info["name"])
        if path is None:
            self._not_found(request)
        return web.FileResponse(path, headers=self.file_headers)


class MemberGifs(_Gifs):
    file_headers = {"Cache-Control": GIF_CACHE}

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get("/gifs", self.index)
        # before /gifs/{action}, which would otherwise take these two for actions
        app.router.add_get(GIF_UPLOAD_PATH, self.upload_form)
        app.router.add_post(GIF_UPLOAD_PATH, self.upload)
        app.router.add_post("/gifs/vote", self.vote)
        app.router.add_get("/gifs/{action}", self.pool)
        app.router.add_get("/gifs/{action}/{pool}", self.pool)  # the cog answers an unknown pool with LookupError
        app.router.add_get("/gifs/{action}/file/{name}", self.file)

    def may_upload(self, member: Any) -> bool:
        """Whether the member may send in a gif; the session middleware asks before it reads a large upload."""
        roleplay: Any = self.cog.bot.get_cog("Roleplay")
        return roleplay is not None and bool(roleplay.can_submit_gif(member))

    def _render(self, request: web.Request, template: str, *, status: int = 200, **context: Any) -> web.Response:
        return self.cog._render(request, f"member/{template}", status=status, **context)

    async def index(self, request: web.Request) -> web.StreamResponse:
        roleplay = self._roleplay(request)
        return self._render(
            request,
            "gifs.html",
            actions=await roleplay.gif_actions(),
            can_upload=roleplay.can_submit_gif(request["member"]),
        )

    async def pool(self, request: web.Request) -> web.StreamResponse:
        roleplay = self._roleplay(request)
        action, pool = request.match_info["action"], request.match_info.get("pool", "default")
        try:
            shown = await roleplay.gif_page(action, pool, request["member"].id, _page(request.query.get("page")))
        except LookupError:
            self._not_found(request)
        return self._render(
            request,
            "gifs_action.html",
            action=action,
            pool=pool,
            can_upload=roleplay.can_submit_gif(request["member"]),
            **shown,
        )

    async def vote(self, request: web.Request) -> web.StreamResponse:
        roleplay = self._roleplay(request)
        form = await request.post()
        action, name, pool = _text(form, "action"), _text(form, "name"), _text(form, "pool")
        value = VOTES.get(_text(form, "value"))
        page, slot = _number(form.get("page"), 1, MAX_PAGE), _number(form.get("slot"), 1, MAX_SLOT)
        if value is None or pool not in POOLS or page is None or slot is None:
            raise web.HTTPBadRequest()
        try:
            await roleplay.gif_vote(request["member"].id, action, name, value)
        except LookupError:
            self._not_found(request)
        if request.headers.get("X-Requested-With") == "fetch":
            return web.Response(status=204)
        raise web.HTTPSeeOther(f"{page_url(action, pool, page)}#g{slot}")

    def _uploader(self, request: web.Request) -> Any:
        """The Roleplay cog, for a member who may send in a gif; anyone else is refused."""
        roleplay = self._roleplay(request)
        if not roleplay.can_submit_gif(request["member"]):
            self._stop(
                request,
                web.HTTPForbidden,
                403,
                "Not allowed",
                "Only supporters and Level 90+ members can send in gifs.",
            )
        return roleplay

    async def upload_form(
        self, request: web.Request, *, chosen: str | None = None, error: str = "", status: int = 200
    ) -> web.StreamResponse:
        """The page to send in a gif from. `?action=` picks the action to start on, as the link on an action's page does."""
        roleplay = self._uploader(request)
        return self._render(
            request,
            "gif_upload.html",
            status=status,
            actions=await roleplay.gif_actions(),
            chosen=request.query.get("action", "") if chosen is None else chosen,
            sent=request.query.get("sent") == "1",
            error=error,
        )

    async def upload(self, request: web.Request) -> web.StreamResponse:
        roleplay = self._uploader(request)
        form = await request.post()
        field, action = form.get("file"), _text(form, "action")
        try:
            if not isinstance(field, web.FileField) or not field.filename:
                raise ValueError("Choose a GIF to send in.")
            try:
                await roleplay.submit_gif(request["member"], action, field.file)
            finally:
                field.file.close()  # the request was cloned for its larger limit, so aiohttp won't close the temp file
        except ValueError as e:
            return await self.upload_form(request, chosen=action, error=str(e), status=400)
        raise web.HTTPSeeOther(f"{GIF_UPLOAD_PATH}?sent=1&action={quote(action, safe='')}")


class StaffGifs(_Gifs):
    def add_routes(self, app: web.Application) -> None:
        app.router.add_get("/gifs", self.votes)
        app.router.add_get("/gifs/{action}/file/{name}", self.file)

    async def votes(self, request: web.Request) -> web.StreamResponse:
        rows = await self._roleplay(request).gif_vote_totals()
        pages = max(1, -(-len(rows) // STAFF_PAGE))
        page = min(_page(request.query.get("page")), pages)
        shown = rows[(page - 1) * STAFF_PAGE : page * STAFF_PAGE]
        return self.cog._render(request, "gif_votes.html", gifs=shown, page=page, pages=pages)
