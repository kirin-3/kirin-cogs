"""Unicornia's web sites behind Discord login: staff.unicornia.net for staff, my.unicornia.net for members.

Both sites listen on loopback only; Caddy exposes them through Cloudflare. They share the login code, parametrized by a
Site record, but keep separate sessions. Every route needs a session unless it is listed in PUBLIC_PATHS, and whether
the user may still use the site is re-checked against the member cache on every request.
"""

import functools
import hmac
import logging
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, cast

import aiohttp
import discord
import jinja2
import markupsafe
from aiohttp import web
from aiohttp.typedefs import Handler
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.errors import CogLoadError
from yarl import URL

from .automod_forms import SECTIONS, Names, apply_action, editor_view, parse_rows, row_templates, row_view
from .member import MemberSite
from .modmail import StaffModmail
from .unicornia_views import StaffUnicornia

GUILD_ID = 684360255798509578
STAFF_ROLE_ID = 696020813299580940
HOST = "127.0.0.1"
STAFF_PORT = 8011
MEMBER_PORT = 8012
REDIRECT_URI = "https://staff.unicornia.net/callback"
MEMBER_REDIRECT_URI = "https://my.unicornia.net/callback"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_API = "https://discord.com/api/v10"
SESSION_COOKIE = "__Host-staff"
MEMBER_COOKIE = "__Host-member"
STATE_COOKIE = "__Host-state"
SESSION_SECONDS = 12 * 3600
STATE_SECONDS = 600
EXCHANGES_PER_IP = 5  # per minute, across both sites
EXCHANGES_TOTAL = 30  # per minute, from all clients on both sites
MEMBER_EXCHANGES = 20  # member logins stop here, so the last 10 of the minute stay free for staff
MEMBER_MAX_BODY = 9 * 1024 * 1024  # an 8 MB custom command attachment plus the rest of the form
PUBLIC_PATHS = frozenset({"/login", "/callback", "/logged-out"})
# POSTs to these routes also need a bot owner; staff can only view automod.
OWNER_ONLY = frozenset(
    {
        "/automod/dryrun",
        "/automod/rulesets",
        "/automod/rulesets/{ruleset_id}",
        "/automod/rulesets/{ruleset_id}/delete",
        "/automod/rulesets/{ruleset_id}/rules",
        "/automod/rules/{rule_id}",
        "/automod/rules/{rule_id}/delete",
        "/automod/lists",
        "/automod/lists/{list_id}",
        "/automod/lists/{list_id}/delete",
    }
)
MAX_WORDS_FORM = 600_000  # characters in a list's textarea
MAX_PAGE = 10_000
MAX_QUERY = 100
DELETED_MODERATOR_ID = 0xDE1
HERE = Path(__file__).parent
# __Host- cookies must be Secure with Path=/ and no Domain, so browsers never share them with other subdomains.
COOKIE_FLAGS: dict[str, Any] = {"httponly": True, "secure": True, "samesite": "Lax", "path": "/"}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src {}; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)
# Modmail attachments are shown from Discord's CDN.
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP.format("'self' https://cdn.discordapp.com"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
}
# Emojis, role icons and avatars are shown from Discord's CDN, rank-card backgrounds from the main site.
MEMBER_SECURITY_HEADERS = {
    **SECURITY_HEADERS,
    "Content-Security-Policy": CSP.format("'self' https://cdn.discordapp.com https://unicornia.net"),
}

log = logging.getLogger("red.kirin-cogs.dashboard")


@dataclass(frozen=True)
class Session:
    user_id: int
    csrf: str
    expires_at: float  # time.monotonic()


@dataclass(frozen=True)
class Site:
    """What differs between the staff and member sites. Ports are read at load time (STAFF_PORT, MEMBER_PORT)."""

    name: str
    redirect_uri: str
    cookie: str
    needs_2fa: bool
    exchange_cap: int  # of the shared per-minute window
    headers: dict[str, str]
    templates: str  # template folder prefix
    login_title: str
    refused_title: str
    refused_text: str


STAFF = Site(
    "staff",
    REDIRECT_URI,
    SESSION_COOKIE,
    True,
    EXCHANGES_TOTAL,
    SECURITY_HEADERS,
    "",
    "Staff login",
    "Staff only",
    "This site is for Unicornia staff.",
)
MEMBER = Site(
    "member",
    MEMBER_REDIRECT_URI,
    MEMBER_COOKIE,
    False,
    MEMBER_EXCHANGES,
    MEMBER_SECURITY_HEADERS,
    "member/",
    "Member login",
    "Members only",
    "This site is for members of the Unicornia Discord server.",
)
SITE = web.AppKey("site", Site)


def _same(given: str, expected: str) -> bool:
    """Constant-time comparison that also accepts non-ASCII input from the request."""
    return hmac.compare_digest(given.encode(), expected.encode())


def _when(timestamp: float | None) -> markupsafe.Markup:
    """A UTC <time> element; site.js rewrites it in the viewer's time zone."""
    if timestamp is None:
        return markupsafe.Markup()
    moment = datetime.fromtimestamp(timestamp, UTC)
    return markupsafe.Markup('<time datetime="{}">{}</time>').format(
        moment.isoformat(), moment.strftime("%Y-%m-%d %H:%M:%S UTC")
    )


def _page_number(raw: str) -> int:
    try:
        return min(max(int(raw), 0), MAX_PAGE)
    except ValueError:
        return 0


_Route = TypeVar("_Route", bound=Callable[..., Awaitable[web.StreamResponse]])


def _editing(handler: _Route) -> _Route:
    """Run an automod route's whole read-modify-save under automod's edit lock."""

    @functools.wraps(handler)
    async def wrapper(self: Any, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return await handler(self, request)
        await request.post()  # read the body before locking; aiohttp caches it for the handler
        async with cog.edit_lock:
            return await handler(self, request)

    return cast(_Route, wrapper)


async def _add_security_headers(request: web.Request, response: web.StreamResponse) -> None:
    response.headers.update(request.app[SITE].headers)


class Dashboard(commands.Cog):
    """Unicornia's staff and member web sites."""

    _runner: web.AppRunner
    _member_runner: web.AppRunner
    _http: aiohttp.ClientSession

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.sessions: dict[str, Session] = {}  # staff
        self.member_sessions: dict[str, Session] = {}
        # (time, client IP) of code exchanges in the last minute, from both sites: they share the bot's IP.
        self._exchanges: deque[tuple[float, str]] = deque()
        self._blocked_until = 0.0
        self._templates = jinja2.Environment(loader=jinja2.FileSystemLoader(HERE / "templates"), autoescape=True)
        self._templates.filters["when"] = _when
        self._templates.globals.update(
            user_name=self._user_name, user_avatar=self._user_avatar, channel_name=self._channel_name
        )
        self.member_site = MemberSite(self)
        self.staff_unicornia = StaffUnicornia(self)
        self.staff_modmail = StaffModmail(self)

    async def cog_load(self) -> None:
        # Not bot.http: that session carries the bot token.
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        # No access log: callback request lines carry OAuth codes.
        self._runner = web.AppRunner(self.make_app(), access_log=None)
        self._member_runner = web.AppRunner(self.make_member_app(), access_log=None)
        for runner, port, name in ((self._runner, STAFF_PORT, "staff"), (self._member_runner, MEMBER_PORT, "member")):
            await runner.setup()
            try:
                await web.TCPSite(runner, HOST, port).start()
            except OSError as exc:
                await self.cog_unload()
                raise CogLoadError(f"The {name} site could not listen on {HOST}:{port} ({exc}).") from exc

    async def cog_unload(self) -> None:
        await self._runner.cleanup()
        await self._member_runner.cleanup()
        await self._http.close()
        self.sessions.clear()
        self.member_sessions.clear()
        self.staff_modmail.links.clear()

    def _app(self, site: Site, **kwargs: Any) -> web.Application:
        """An app with the login routes and access control shared by both sites."""
        app = web.Application(middlewares=[self._require_session], **kwargs)
        app[SITE] = site
        app.on_response_prepare.append(_add_security_headers)
        app.router.add_get("/login", self.login)
        app.router.add_get("/callback", self.callback)
        app.router.add_get("/logged-out", self.logged_out)
        app.router.add_post("/logout", self.logout)
        app.router.add_static("/static", HERE / "static")
        return app

    def make_member_app(self) -> web.Application:
        app = self._app(MEMBER, client_max_size=MEMBER_MAX_BODY)
        self.member_site.add_routes(app)
        return app

    def make_app(self) -> web.Application:
        app = self._app(STAFF)
        app.router.add_get("/", self.ban_list)
        app.router.add_get(r"/bans/{ban_id:\d{1,18}}", self.ban_detail)
        ruleset, rule, word_list = r"{ruleset_id:\d{1,18}}", r"{rule_id:\d{1,18}}", r"{list_id:\d{1,18}}"
        app.router.add_get("/automod", self.automod_overview)
        app.router.add_get("/automod/log", self.automod_log)
        app.router.add_get(f"/automod/rulesets/{ruleset}", self.automod_ruleset)
        app.router.add_get(f"/automod/lists/{word_list}", self.automod_list)
        app.router.add_post("/automod/dryrun", self.automod_dry_run)
        app.router.add_post("/automod/rulesets", self.automod_ruleset_create)
        app.router.add_post(f"/automod/rulesets/{ruleset}", self.automod_ruleset_save)
        app.router.add_post(f"/automod/rulesets/{ruleset}/delete", self.automod_ruleset_delete)
        app.router.add_post(f"/automod/rulesets/{ruleset}/rules", self.automod_rule_create)
        app.router.add_post(f"/automod/rules/{rule}", self.automod_rule_save)
        app.router.add_post(f"/automod/rules/{rule}/delete", self.automod_rule_delete)
        app.router.add_post("/automod/lists", self.automod_list_create)
        app.router.add_post(f"/automod/lists/{word_list}", self.automod_list_save)
        app.router.add_post(f"/automod/lists/{word_list}/delete", self.automod_list_delete)
        self.staff_unicornia.add_routes(app)
        self.staff_modmail.add_routes(app)
        return app

    # --- access control --------------------------------------------------------------------------

    @web.middleware
    async def _require_session(self, request: web.Request, handler: Handler) -> web.StreamResponse:
        """Deny by default: only PUBLIC_PATHS, static files, and unmatched URLs (404/405) skip the session check."""
        resource = request.match_info.route.resource
        if resource is None or isinstance(resource, web.StaticResource) or resource.canonical in PUBLIC_PATHS:
            return await handler(request)
        session = self._session(request)
        if session is None:
            if request.method in ("GET", "HEAD"):
                raise web.HTTPFound("/logged-out")
            raise web.HTTPUnauthorized()
        if request.method == "POST":
            # Read only now that the session is known, so anonymous clients can't make the bot buffer uploads.
            form = await request.post()
            if not _same(str(form.get("csrf", "")), session.csrf):
                raise web.HTTPForbidden()
            if resource.canonical in OWNER_ONLY and not await self._is_owner(session.user_id):
                raise web.HTTPForbidden()
        request["session"] = session
        if request.app[SITE] is MEMBER:
            member = self.member(session.user_id)
            assert member is not None  # _session() checked
            request["member"] = member
            request["nav"] = await self.member_site.sections(member)
        return await handler(request)

    def _sessions(self, site: Site) -> dict[str, Session]:
        return self.sessions if site is STAFF else self.member_sessions

    def _session(self, request: web.Request) -> Session | None:
        """The request's live session; expired sessions and users the site no longer admits are logged out on the spot."""
        site = request.app[SITE]
        sessions = self._sessions(site)
        token = request.cookies.get(site.cookie, "")
        session = sessions.get(token)
        if session is None:
            return None
        if session.expires_at <= time.monotonic() or not self._admits(site, session.user_id):
            del sessions[token]
            return None
        return session

    def _admits(self, site: Site, user_id: int) -> bool:
        return self._is_staff(user_id) if site is STAFF else self.member(user_id) is not None

    def guild(self) -> discord.Guild | None:
        return self.bot.get_guild(GUILD_ID)

    def member(self, user_id: int) -> discord.Member | None:
        """The user as a Unicornia member, from the bot's member cache."""
        guild = self.guild()
        return guild.get_member(user_id) if guild else None

    def _is_staff(self, user_id: int) -> bool:
        """The same gate as [p]ban: the staff role or Ban Members, read from the bot's member cache."""
        member = self.member(user_id)
        return member is not None and (
            member.get_role(STAFF_ROLE_ID) is not None or member.guild_permissions.ban_members
        )

    async def _is_owner(self, user_id: int) -> bool:
        member = self.member(user_id)
        return member is not None and await self.bot.is_owner(member)

    def _allow_exchange(self, ip: str, cap: int = EXCHANGES_TOTAL) -> bool:
        """Cap code exchanges so a login flood can't get the bot's shared IP banned by Discord.

        Both sites share one window; the member site passes a lower cap, so it can't use up the staff site's share.
        """
        now = time.monotonic()
        if now < self._blocked_until:
            return False
        while self._exchanges and self._exchanges[0][0] <= now - 60:
            self._exchanges.popleft()
        recent_from_ip = sum(seen == ip for _, seen in self._exchanges)
        if len(self._exchanges) >= min(cap, EXCHANGES_TOTAL) or recent_from_ip >= EXCHANGES_PER_IP:
            return False
        self._exchanges.append((now, ip))
        return True

    # --- login -----------------------------------------------------------------------------------

    async def _client_secret(self) -> str | None:
        return (await self.bot.get_shared_api_tokens("dashboard")).get("client_secret")

    async def login(self, request: web.Request) -> web.StreamResponse:
        if not await self._client_secret():
            return self._not_configured(request)
        state = secrets.token_urlsafe(32)
        url = URL(AUTHORIZE_URL).with_query(
            client_id=str(self.bot.application_id),
            response_type="code",
            scope="identify",
            redirect_uri=request.app[SITE].redirect_uri,
            state=state,
            prompt="none",
        )
        response = web.Response(status=302, headers={"Location": str(url)})
        # Only the browser that started the login can finish it, which defeats login CSRF.
        response.set_cookie(STATE_COOKIE, state, max_age=STATE_SECONDS, **COOKIE_FLAGS)
        return response

    async def callback(self, request: web.Request) -> web.StreamResponse:
        site = request.app[SITE]
        state = request.query.get("state", "")
        if not state or not _same(state, request.cookies.get(STATE_COOKIE, "")):
            return self._message(request, 400, "Login expired", "Start again from the login page.", login=True)
        code = request.query.get("code")
        if not code:
            return self._login_failed(request)  # cancelled on Discord's page
        if not self._allow_exchange(request.headers.get("CF-Connecting-IP") or request.remote or "", site.exchange_cap):
            return self._message(request, 429, "Too many logins", "Wait a minute, then try again.", login=True)
        secret = await self._client_secret()
        if not secret:
            return self._not_configured(request)
        try:
            user = await self._fetch_identity(code, secret, site.redirect_uri)
        except (aiohttp.ClientError, TimeoutError, KeyError, ValueError):
            log.warning("Discord login request failed", exc_info=True)
            user = None
        if user is None:
            return self._login_failed(request)
        if site.needs_2fa and not user.get("mfa_enabled"):
            text = "Turn on two-factor authentication for your Discord account, then log in again."
            return self._message(request, 403, "Two-factor authentication required", text, login=True)
        user_id = int(user["id"])
        if not self._admits(site, user_id):
            return self._message(request, 403, site.refused_title, site.refused_text)
        return self._start_session(request, user_id)

    async def _fetch_identity(self, code: str, secret: str, redirect_uri: str) -> dict[str, Any] | None:
        """Trade the code for the user's identity. The access token is used once and never stored."""
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        auth = aiohttp.BasicAuth(str(self.bot.application_id), secret)
        async with self._http.post(f"{DISCORD_API}/oauth2/token", data=data, auth=auth) as response:
            if not self._discord_ok(response):
                return None
            token = (await response.json())["access_token"]
        async with self._http.get(f"{DISCORD_API}/users/@me", headers={"Authorization": f"Bearer {token}"}) as response:
            if not self._discord_ok(response):
                return None
            return await response.json()

    def _discord_ok(self, response: aiohttp.ClientResponse) -> bool:
        if response.status == 429:
            # Stop calling Discord until it allows us again; it bans IPs that keep hitting its limits.
            try:
                retry_after = float(response.headers.get("Retry-After", "60"))
            except ValueError:
                retry_after = 60.0
            self._blocked_until = time.monotonic() + max(retry_after, 1.0)
            log.warning("Discord rate-limited a login; pausing logins on both sites for %.0f seconds", retry_after)
        return response.status == 200

    def _start_session(self, request: web.Request, user_id: int) -> web.Response:
        site = request.app[SITE]
        sessions = self._sessions(site)
        now = time.monotonic()
        for token in [token for token, session in sessions.items() if session.expires_at <= now]:
            del sessions[token]
        sessions.pop(request.cookies.get(site.cookie, ""), None)  # never reuse a token from before login
        token = secrets.token_urlsafe(32)
        sessions[token] = Session(user_id, secrets.token_urlsafe(32), now + SESSION_SECONDS)
        response = web.Response(status=302, headers={"Location": "/"})
        response.set_cookie(site.cookie, token, max_age=SESSION_SECONDS, **COOKIE_FLAGS)
        response.set_cookie(STATE_COOKIE, "", max_age=0, **COOKIE_FLAGS)
        return response

    async def logout(self, request: web.Request) -> web.StreamResponse:
        site = request.app[SITE]
        self._sessions(site).pop(request.cookies.get(site.cookie, ""), None)
        response = web.Response(status=302, headers={"Location": "/logged-out"})
        response.set_cookie(site.cookie, "", max_age=0, **COOKIE_FLAGS)
        return response

    async def logged_out(self, request: web.Request) -> web.StreamResponse:
        title = request.app[SITE].login_title
        return self._message(request, 200, title, "Log in with your Discord account to continue.", login=True)

    # --- ban pages ---------------------------------------------------------------------------------

    async def ban_list(self, request: web.Request) -> web.StreamResponse:
        query = request.query.get("q", "").strip()[:MAX_QUERY]
        page = _page_number(request.query.get("page", "0"))
        banlog = self.bot.get_cog("BanLog")
        if banlog is None:
            return self._render(request, "bans.html", missing=True, q=query)
        bans, more = await cast(Any, banlog).list_bans(page, query)
        return self._render(request, "bans.html", bans=bans, more=more, page=page, q=query)

    async def ban_detail(self, request: web.Request) -> web.StreamResponse:
        banlog = self.bot.get_cog("BanLog")
        if banlog is None:
            return self._render(request, "ban.html", missing=True)
        ban = await cast(Any, banlog).get_ban(int(request.match_info["ban_id"]))
        if ban is None:
            return self._message(request, 404, "Ban not found", "There is no ban record with that number.")
        modmail_threads = await self.staff_modmail.for_user(int(ban["user_id"]))
        return self._render(request, "ban.html", ban=ban, modmail_threads=modmail_threads)

    # --- automod pages -----------------------------------------------------------------------------

    def _automod(self) -> Any:
        return self.bot.get_cog("AutoMod")

    async def _owner(self, request: web.Request) -> bool:
        session = request.get("session")
        return session is not None and await self._is_owner(session.user_id)

    def _names(self, document: dict) -> Names:
        guild = self.bot.get_guild(GUILD_ID)
        roles, channels = {}, {}
        if guild is not None:
            roles = {r.id: r.name for r in sorted(guild.roles, reverse=True) if not r.is_default()}
            channels = {
                c.id: c.name
                for c in sorted(guild.channels, key=lambda c: c.position)
                if not isinstance(c, discord.CategoryChannel)
            }
        return Names(roles, channels, {item["id"]: item["name"] for item in document["lists"]})

    def _automod_missing(self, request: web.Request) -> web.Response:
        return self._render(request, "automod.html", missing=True, status=503 if request.method == "POST" else 200)

    async def automod_overview(self, request: web.Request, *, error: str = "", status: int = 200) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        document = await cog.document()
        return self._render(
            request,
            "automod.html",
            status=status,
            document=document,
            dry_run=cog.dry_run,
            is_owner=await self._owner(request),
            error=error,
        )

    async def automod_log(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        return self._render(request, "automod_log.html", entries=await cog.action_log())

    @staticmethod
    def _find(document: dict, kind: str, item_id: int) -> tuple[dict, dict] | None:
        """(ruleset, rule) for a rule, (ruleset, ruleset) for a ruleset, (list, list) for a list."""
        if kind == "list":
            found = next((item for item in document["lists"] if item["id"] == item_id), None)
            return (found, found) if found else None
        for ruleset in document["rulesets"]:
            if kind == "ruleset" and ruleset["id"] == item_id:
                return ruleset, ruleset
            for rule in ruleset["rules"] if kind == "rule" else ():
                if rule["id"] == item_id:
                    return ruleset, rule
        return None

    def _not_found(self, request: web.Request, what: str) -> web.Response:
        return self._message(request, 404, f"{what} not found", f"There is no automod {what.lower()} with that number.")

    async def automod_ruleset(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        document = await cog.document()
        found = self._find(document, "ruleset", int(request.match_info["ruleset_id"]))
        if found is None:
            return self._not_found(request, "Ruleset")
        return await self._ruleset_page(request, cog, document, found[0])

    async def _ruleset_page(
        self,
        request: web.Request,
        cog: Any,
        document: dict,
        ruleset: dict,
        *,
        drafts: dict[Any, tuple[dict, str]] | None = None,
        status: int = 200,
    ) -> web.Response:
        """The ruleset with every rule. `drafts` maps a rule id, "new" or "settings" to (unsaved draft, error)."""
        registry, names, drafts = cog.registry, self._names(document), drafts or {}

        def editor(key: Any, stored: dict, sections: tuple[str, ...]) -> dict:
            draft, error = drafts.get(key, (stored, ""))
            return {
                "name": draft["name"],
                "enabled": draft.get("enabled"),
                "sections": editor_view(registry, draft, names, sections),
                "error": error,
                "open": key in drafts,
            }

        def read_only(item: dict, sections: tuple[str, ...]) -> dict:
            return {s: [row_view(registry, s, n, row, names) for n, row in enumerate(item[s])] for s in sections}

        blank = {"name": "", "triggers": [], "conditions": [], "effects": []}
        rules = [
            {
                "id": rule["id"],
                "name": rule["name"],
                "view": read_only(rule, SECTIONS),
                "editor": editor(rule["id"], rule, SECTIONS),
            }
            for rule in ruleset["rules"]
        ]
        return self._render(
            request,
            "automod_ruleset.html",
            status=status,
            ruleset=ruleset,
            conditions=read_only(ruleset, ("conditions",))["conditions"],
            settings=editor("settings", ruleset, ("conditions",)),
            rules=rules,
            new_rule=editor("new", blank, SECTIONS),
            row_templates=row_templates(registry, names, SECTIONS),
            is_owner=await self._owner(request),
        )

    async def automod_list(
        self, request: web.Request, *, draft: dict | None = None, error: str = ""
    ) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        document = await cog.document()
        found = self._find(document, "list", int(request.match_info["list_id"]))
        if found is None:
            return self._not_found(request, "List")
        return self._render(
            request,
            "automod_list.html",
            status=400 if error else 200,
            item=found[0],
            draft=draft or found[0],
            users=cog.registry.list_users(document, found[0]["id"]),
            error=error,
            is_owner=await self._owner(request),
        )

    # --- automod changes (owner only, see OWNER_ONLY) ------------------------------------------------

    async def _save(self, cog: Any, document: dict) -> str:
        """Store the document; returns the validation error, or "" when saved."""
        try:
            await cog.save(document)
        except cog.registry.RuleError as e:
            return str(e)
        return ""

    async def automod_dry_run(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        form = await request.post()
        await cog.set_dry_run(form.get("dry_run") == "on")
        raise web.HTTPFound("/automod")

    @_editing
    async def automod_ruleset_create(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        form = await request.post()
        document = await cog.document()
        new_id = document["next_id"]
        document["next_id"] += 1
        name = str(form.get("name", "")).strip()
        document["rulesets"].append({"id": new_id, "name": name, "enabled": True, "conditions": [], "rules": []})
        if error := await self._save(cog, document):
            return await self.automod_overview(request, error=error, status=400)
        raise web.HTTPFound(f"/automod/rulesets/{new_id}")

    @_editing
    async def automod_ruleset_save(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        form = await request.post()
        document = await cog.document()
        found = self._find(document, "ruleset", int(request.match_info["ruleset_id"]))
        if found is None:
            return self._not_found(request, "Ruleset")
        ruleset = found[0]
        draft = {
            "name": str(form.get("name", "")).strip(),
            "enabled": "enabled" in form,
            "conditions": parse_rows(form, cog.registry, "conditions"),
        }
        action = str(form.get("action", "save"))
        if action != "save":
            apply_action(action, draft, form, cog.registry, ("conditions",))
            return await self._ruleset_page(request, cog, document, ruleset, drafts={"settings": (draft, "")})
        ruleset.update(draft)
        if error := await self._save(cog, document):
            document = await cog.document()
            ruleset = self._find(document, "ruleset", ruleset["id"])[0]  # type: ignore[index]
            return await self._ruleset_page(
                request, cog, document, ruleset, drafts={"settings": (draft, error)}, status=400
            )
        raise web.HTTPFound(f"/automod/rulesets/{ruleset['id']}")

    @_editing
    async def automod_ruleset_delete(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        document = await cog.document()
        ruleset_id = int(request.match_info["ruleset_id"])
        document["rulesets"] = [r for r in document["rulesets"] if r["id"] != ruleset_id]
        if error := await self._save(cog, document):
            return await self.automod_overview(request, error=error, status=400)
        raise web.HTTPFound("/automod")

    @_editing
    async def automod_rule_create(self, request: web.Request) -> web.StreamResponse:
        return await self._rule_submit(request, "ruleset", int(request.match_info["ruleset_id"]))

    @_editing
    async def automod_rule_save(self, request: web.Request) -> web.StreamResponse:
        return await self._rule_submit(request, "rule", int(request.match_info["rule_id"]))

    async def _rule_submit(self, request: web.Request, kind: str, item_id: int) -> web.StreamResponse:
        """Save a rule, or rebuild the page with the unsaved draft for add/remove row buttons and errors."""
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        form = await request.post()
        document = await cog.document()
        found = self._find(document, kind, item_id)
        if found is None:
            return self._not_found(request, "Rule" if kind == "rule" else "Ruleset")
        ruleset, rule = found[0], found[1] if kind == "rule" else None
        key = rule["id"] if rule else "new"
        draft = {"name": str(form.get("name", "")).strip()}
        draft |= {section: parse_rows(form, cog.registry, section) for section in SECTIONS}
        action = str(form.get("action", "save"))
        if action != "save":
            apply_action(action, draft, form, cog.registry, SECTIONS)
            return await self._ruleset_page(request, cog, document, ruleset, drafts={key: (draft, "")})
        if rule is not None:
            rule.update(draft)
            rule_id = rule["id"]
        else:
            rule_id = document["next_id"]
            document["next_id"] += 1
            ruleset["rules"].append({"id": rule_id, **draft})
        if error := await self._save(cog, document):
            document = await cog.document()
            ruleset = self._find(document, "ruleset", ruleset["id"])[0]  # type: ignore[index]
            return await self._ruleset_page(request, cog, document, ruleset, drafts={key: (draft, error)}, status=400)
        raise web.HTTPFound(f"/automod/rulesets/{ruleset['id']}#rule-{rule_id}")

    @_editing
    async def automod_rule_delete(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        document = await cog.document()
        found = self._find(document, "rule", int(request.match_info["rule_id"]))
        if found is None:
            return self._not_found(request, "Rule")
        ruleset, rule = found
        ruleset["rules"].remove(rule)
        if error := await self._save(cog, document):
            return await self.automod_overview(request, error=error, status=400)
        raise web.HTTPFound(f"/automod/rulesets/{ruleset['id']}")

    @_editing
    async def automod_list_create(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        form = await request.post()
        document = await cog.document()
        new_id = document["next_id"]
        document["next_id"] += 1
        document["lists"].append({"id": new_id, "name": str(form.get("name", "")).strip(), "words": []})
        if error := await self._save(cog, document):
            return await self.automod_overview(request, error=error, status=400)
        raise web.HTTPFound(f"/automod/lists/{new_id}")

    @_editing
    async def automod_list_save(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        form = await request.post()
        document = await cog.document()
        found = self._find(document, "list", int(request.match_info["list_id"]))
        if found is None:
            return self._not_found(request, "List")
        item = found[0]
        words = str(form.get("words", ""))[:MAX_WORDS_FORM].splitlines()
        draft = {**item, "name": str(form.get("name", "")).strip(), "words": words}
        item.update(draft)
        if error := await self._save(cog, document):
            return await self.automod_list(request, draft=draft, error=error)
        raise web.HTTPFound(f"/automod/lists/{item['id']}")

    @_editing
    async def automod_list_delete(self, request: web.Request) -> web.StreamResponse:
        cog = self._automod()
        if cog is None:
            return self._automod_missing(request)
        document = await cog.document()
        list_id = int(request.match_info["list_id"])
        if users := cog.registry.list_users(document, list_id):
            return await self.automod_list(request, error="This list is used by " + ", ".join(users) + ".")
        document["lists"] = [item for item in document["lists"] if item["id"] != list_id]
        if error := await self._save(cog, document):
            return await self.automod_overview(request, error=error, status=400)
        raise web.HTTPFound("/automod")

    # --- rendering ---------------------------------------------------------------------------------

    def _render(self, request: web.Request, template: str, *, status: int = 200, **context: Any) -> web.Response:
        html = self._templates.get_template(template).render(
            session=request.get("session"), path=request.path, nav=request.get("nav"), **context
        )
        return web.Response(text=html, status=status, content_type="text/html")

    def _message(
        self, request: web.Request, status: int, title: str, text: str, *, login: bool = False
    ) -> web.Response:
        template = request.app[SITE].templates + "message.html"
        return self._render(request, template, status=status, title=title, text=text, login=login)

    def _login_failed(self, request: web.Request) -> web.Response:
        return self._message(request, 400, "Login failed", "Discord did not confirm the login.", login=True)

    def _not_configured(self, request: web.Request) -> web.Response:
        text = "The bot owner has not set the Discord client secret yet."
        return self._message(request, 503, "Login is not set up", text)

    def _user_name(self, user_id: int | None) -> str:
        if user_id is None:
            return "Unknown"
        if user_id == DELETED_MODERATOR_ID:
            return "Deleted user"
        user = self.bot.get_user(user_id)
        return user.name if user else str(user_id)

    def _user_avatar(self, user_id: int) -> str:
        """The user's Discord avatar URL, or ""."""
        user = self.bot.get_user(user_id)
        return user.display_avatar.with_size(128).url if user else ""

    def _channel_name(self, channel_id: int) -> str:
        guild = self.bot.get_guild(GUILD_ID)
        channel = guild.get_channel_or_thread(channel_id) if guild else None
        return f"#{channel.name}" if channel else str(channel_id)
