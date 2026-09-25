"""Tests for the staff site: server lifecycle, login, sessions, access control, throttling, and ban pages."""

import re
import secrets
import socket
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from redbot.core.errors import CogLoadError
from yarl import URL

import dashboard.dashboard as dashboard_module
from dashboard.dashboard import (
    PUBLIC_PATHS,
    SECURITY_HEADERS,
    SESSION_COOKIE,
    STAFF_ROLE_ID,
    STATE_COOKIE,
    Dashboard,
    Session,
)

STAFF_ID = 200000000000000001
CSRF = "csrf-token"


class _FakeResponse:
    def __init__(self, status: int, body: Any = None, headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.body = body
        self.headers = headers or {}

    async def json(self) -> Any:
        return self.body

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _FakeDiscord:
    """Stands in for the cog's aiohttp session and records every request sent to Discord."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.token = _FakeResponse(200, {"access_token": "access"})
        self.me = _FakeResponse(200, {"id": str(STAFF_ID), "mfa_enabled": True})

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(url)
        return self.token

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append(url)
        return self.me


class _FakeBanLog:
    def __init__(self) -> None:
        self.bans: list[dict[str, Any]] = []
        self.more = False
        self.searches: list[tuple[int, str]] = []
        self.records: dict[int, dict[str, Any]] = {}

    async def list_bans(self, page: int, query: str) -> tuple[list[dict[str, Any]], bool]:
        self.searches.append((page, query))
        return self.bans, self.more

    async def get_ban(self, ban_id: int) -> dict[str, Any] | None:
        return self.records.get(ban_id)


def _member(*, staff: bool = False, ban_members: bool = False) -> MagicMock:
    member = MagicMock()
    member.get_role.side_effect = lambda role_id: object() if staff and role_id == STAFF_ROLE_ID else None
    member.guild_permissions.ban_members = ban_members
    return member


@pytest_asyncio.fixture
async def site() -> AsyncIterator[SimpleNamespace]:
    bot = MagicMock()
    bot.application_id = 111
    bot.get_shared_api_tokens = AsyncMock(return_value={"client_secret": "secret"})
    bot.get_user.return_value = None
    bot.get_cog.return_value = None
    members: dict[int, MagicMock] = {STAFF_ID: _member(staff=True)}
    guild = MagicMock()
    guild.get_member.side_effect = members.get
    guild.get_channel_or_thread.return_value = None
    bot.get_guild.return_value = guild
    cog = Dashboard(bot)
    fake_discord = _FakeDiscord()
    cog._http = fake_discord  # type: ignore[assignment]
    client = TestClient(TestServer(cog.make_app()))
    await client.start_server()
    yield SimpleNamespace(cog=cog, bot=bot, guild=guild, members=members, client=client, discord=fake_discord)
    await client.close()


def _log_in(site: SimpleNamespace, user_id: int = STAFF_ID, *, expires_in: float = 3600) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    site.cog.sessions[token] = Session(user_id, CSRF, time.monotonic() + expires_in)
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


async def _callback(site: SimpleNamespace, *, ip: str = "203.0.113.1", state: str = "s", cookie: str | None = "s"):
    headers = {"CF-Connecting-IP": ip}
    if cookie is not None:
        headers["Cookie"] = f"{STATE_COOKIE}={cookie}"
    return await site.client.get(
        "/callback", params={"state": state, "code": "code"}, headers=headers, allow_redirects=False
    )


def _set_cookie(response: aiohttp.ClientResponse, name: str) -> str:
    [header] = [value for value in response.headers.getall("Set-Cookie") if value.startswith(f"{name}=")]
    return header


def _assert_host_only(header: str) -> None:
    flags = [part.strip().lower() for part in header.split(";")[1:]]
    assert {"httponly", "secure", "samesite=lax", "path=/"} <= set(flags)
    assert not any(flag.startswith("domain") for flag in flags)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# --- server lifecycle ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_site_listens_on_loopback_until_unloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    monkeypatch.setattr(dashboard_module, "STAFF_PORT", port)
    cog = Dashboard(MagicMock())
    await cog.cog_load()
    async with aiohttp.ClientSession() as http:
        async with http.get(f"http://127.0.0.1:{port}/logged-out") as response:
            assert response.status == 200
        cog.sessions["x"] = Session(1, CSRF, time.monotonic() + 60)

        await cog.cog_unload()

        assert cog.sessions == {}
        with pytest.raises(aiohttp.ClientConnectorError):
            await http.get(f"http://127.0.0.1:{port}/logged-out")


@pytest.mark.asyncio
async def test_port_in_use_fails_the_load_and_names_the_port(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        monkeypatch.setattr(dashboard_module, "STAFF_PORT", port)
        cog = Dashboard(MagicMock())

        with pytest.raises(CogLoadError, match=str(port)):
            await cog.cog_load()

        assert cog._http.closed
        assert cog._runner.server is None


# --- rendering and headers -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_security_headers_on_public_and_protected_pages(site: SimpleNamespace) -> None:
    site.bot.get_cog.return_value = _FakeBanLog()
    public = await site.client.get("/logged-out")
    protected = await site.client.get("/", headers=_log_in(site))
    redirect = await site.client.get("/", allow_redirects=False)

    for response in (public, protected, redirect):
        for name, value in SECURITY_HEADERS.items():
            assert response.headers[name] == value
    assert protected.status == 200


@pytest.mark.asyncio
async def test_only_the_sites_own_script_may_run(site: SimpleNamespace) -> None:
    policy = SECURITY_HEADERS["Content-Security-Policy"]
    assert "script-src 'self';" in policy and "unsafe" not in policy and "connect-src" not in policy
    # nosniff blocks a script served with the wrong type.
    script = await site.client.get("/static/site.js")
    assert script.status == 200 and "javascript" in script.headers["Content-Type"]


@pytest.mark.asyncio
async def test_user_text_is_escaped(site: SimpleNamespace) -> None:
    banlog = _FakeBanLog()
    banlog.bans = [
        {
            "id": 1,
            "user_id": 5,
            "username": "<script>alert(1)</script>",
            "moderator_id": None,
            "reason": "<b>x</b>",
            "banned_at": 0.0,
            "unbanned_at": None,
            "message_count": 0,
        }
    ]
    site.bot.get_cog.return_value = banlog

    body = await (await site.client.get("/", headers=_log_in(site))).text()

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<script>" not in body and "<b>" not in body


# --- login ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_redirects_to_discord_with_a_state_cookie(site: SimpleNamespace) -> None:
    response = await site.client.get("/login", allow_redirects=False)

    assert response.status == 302
    location = URL(response.headers["Location"])
    assert str(location.with_query(None)) == "https://discord.com/oauth2/authorize"
    assert location.query["scope"] == "identify"
    assert location.query["prompt"] == "none"
    assert location.query["redirect_uri"] == "https://staff.unicornia.net/callback"
    header = _set_cookie(response, STATE_COOKIE)
    assert header.startswith(f"{STATE_COOKIE}={location.query['state']};")
    assert "Max-Age=600" in header
    _assert_host_only(header)


@pytest.mark.asyncio
async def test_login_without_client_secret_explains_instead_of_redirecting(site: SimpleNamespace) -> None:
    site.bot.get_shared_api_tokens.return_value = {}

    response = await site.client.get("/login", allow_redirects=False)

    assert response.status == 503
    assert "not set up" in await response.text()
    assert STATE_COOKIE not in response.cookies


@pytest.mark.parametrize(("state", "cookie"), [("s", "other"), ("s", None), ("", "")])
@pytest.mark.asyncio
async def test_state_mismatch_is_rejected_without_calling_discord(
    site: SimpleNamespace, state: str, cookie: str | None
) -> None:
    response = await _callback(site, state=state, cookie=cookie)

    assert response.status == 400
    assert site.discord.calls == []
    assert site.cog.sessions == {}


@pytest.mark.asyncio
async def test_rejected_code_shows_login_failed(site: SimpleNamespace) -> None:
    site.discord.token = _FakeResponse(400, {"error": "invalid_grant"})

    response = await _callback(site)

    assert response.status == 400
    assert "Login failed" in await response.text()
    assert site.cog.sessions == {}


@pytest.mark.parametrize(
    ("me", "members", "expected"),
    [
        ({"id": str(STAFF_ID), "mfa_enabled": False}, {STAFF_ID: _member(staff=True)}, "Two-factor"),
        ({"id": str(STAFF_ID), "mfa_enabled": True}, {STAFF_ID: _member()}, "Staff only"),
        ({"id": str(STAFF_ID), "mfa_enabled": True}, {}, "Staff only"),
    ],
    ids=["no-2fa", "not-staff", "not-a-member"],
)
@pytest.mark.asyncio
async def test_login_refused(site: SimpleNamespace, me: dict[str, Any], members: dict, expected: str) -> None:
    site.discord.me = _FakeResponse(200, me)
    site.members.clear()
    site.members.update(members)

    response = await _callback(site)

    assert response.status == 403
    assert expected in await response.text()
    assert site.cog.sessions == {}


@pytest.mark.parametrize("member", [_member(staff=True), _member(ban_members=True)], ids=["staff-role", "ban-members"])
@pytest.mark.asyncio
async def test_staff_login_creates_a_session(site: SimpleNamespace, member: MagicMock) -> None:
    site.members[STAFF_ID] = member

    response = await _callback(site)

    assert response.status == 302 and response.headers["Location"] == "/"
    [(token, session)] = site.cog.sessions.items()
    assert session.user_id == STAFF_ID
    header = _set_cookie(response, SESSION_COOKIE)
    assert header.startswith(f"{SESSION_COOKIE}={token};") and len(token) >= 43
    _assert_host_only(header)
    assert (await site.client.get("/", headers={"Cookie": f"{SESSION_COOKIE}={token}"})).status == 200


# --- sessions ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_session_is_logged_out(site: SimpleNamespace) -> None:
    headers = _log_in(site, expires_in=-1)

    response = await site.client.get("/", headers=headers, allow_redirects=False)

    assert response.headers["Location"] == "/logged-out"
    assert site.cog.sessions == {}


@pytest.mark.asyncio
async def test_unknown_session_cookie_is_logged_out(site: SimpleNamespace) -> None:
    response = await site.client.get("/", headers={"Cookie": f"{SESSION_COOKIE}=forged"}, allow_redirects=False)

    assert response.headers["Location"] == "/logged-out"


@pytest.mark.asyncio
async def test_logout_needs_the_csrf_token(site: SimpleNamespace) -> None:
    headers = _log_in(site)

    refused = await site.client.post("/logout", data={}, headers=headers, allow_redirects=False)
    assert refused.status == 403 and len(site.cog.sessions) == 1

    done = await site.client.post("/logout", data={"csrf": CSRF}, headers=headers, allow_redirects=False)
    assert done.status == 302 and done.headers["Location"] == "/logged-out"
    assert site.cog.sessions == {}
    after = await site.client.get("/", headers=headers, allow_redirects=False)
    assert after.headers["Location"] == "/logged-out"


# --- access control ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_protected_route_rejects_anonymous_visitors(site: SimpleNamespace) -> None:
    site.bot.get_cog.return_value = _FakeBanLog()
    checked = 0
    for route in site.client.app.router.routes():
        resource = route.resource
        if resource is None or isinstance(resource, web.StaticResource) or resource.canonical in PUBLIC_PATHS:
            continue
        path = re.sub(r"\{[^}]+\}", "1", resource.canonical)
        response = await site.client.request(route.method, path, allow_redirects=False)
        if route.method in ("GET", "HEAD"):
            assert (response.status, response.headers["Location"]) == (302, "/logged-out"), path
        else:
            assert response.status == 401, path
        checked += 1
    assert checked >= 4  # GET and HEAD for / and /bans/{id}, POST /logout


@pytest.mark.parametrize("change", ["role-removed", "left-server"])
@pytest.mark.asyncio
async def test_losing_staff_status_ends_the_session(site: SimpleNamespace, change: str) -> None:
    headers = _log_in(site)
    if change == "role-removed":
        site.members[STAFF_ID] = _member()
    else:
        del site.members[STAFF_ID]

    response = await site.client.get("/", headers=headers, allow_redirects=False)

    assert response.headers["Location"] == "/logged-out"
    assert site.cog.sessions == {}


# --- exchange throttling -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sixth_exchange_from_one_ip_is_throttled(site: SimpleNamespace) -> None:
    site.discord.token = _FakeResponse(400)
    statuses = [(await _callback(site)).status for _ in range(6)]

    assert statuses == [400] * 5 + [429]
    assert len(site.discord.calls) == 5


@pytest.mark.asyncio
async def test_thirty_first_exchange_overall_is_throttled(site: SimpleNamespace) -> None:
    site.discord.token = _FakeResponse(400)
    for n in range(30):
        await _callback(site, ip=f"198.51.100.{n}")

    response = await _callback(site, ip="192.0.2.99")

    assert response.status == 429
    assert len(site.discord.calls) == 30


@pytest.mark.asyncio
async def test_discord_429_pauses_every_exchange(site: SimpleNamespace) -> None:
    site.discord.token = _FakeResponse(429, {"retry_after": 30}, {"Retry-After": "30"})
    await _callback(site)
    assert len(site.discord.calls) == 1

    responses = [await _callback(site, ip=f"192.0.2.{n}") for n in range(3)]

    assert [response.status for response in responses] == [429] * 3
    assert len(site.discord.calls) == 1


# --- ban pages -----------------------------------------------------------------------------------


def _ban(ban_id: int, **overrides: Any) -> dict[str, Any]:
    return {
        "id": ban_id,
        "user_id": 300000000000000001,
        "username": "spammer",
        "moderator_id": 0xDE1,
        "reason": "links",
        "banned_at": 1_700_000_000.0,
        "unbanned_at": None,
        "message_count": 2,
        **overrides,
    }


@pytest.mark.asyncio
async def test_ban_list_shows_records_and_next_page(site: SimpleNamespace) -> None:
    banlog = _FakeBanLog()
    banlog.bans = [_ban(7)]
    banlog.more = True
    site.bot.get_cog.return_value = banlog

    body = await (await site.client.get("/", params={"page": "2", "q": "spam"}, headers=_log_in(site))).text()

    assert banlog.searches == [(2, "spam")]
    assert 'href="/bans/7"' in body and "spammer" in body and "Deleted user" in body and "links" in body
    assert "2023-11-14 22:13:20 UTC" in body
    assert 'href="/?page=3&amp;q=spam"' in body and 'href="/?page=1&amp;q=spam"' in body


@pytest.mark.asyncio
async def test_ban_pages_without_banlog_show_a_notice(site: SimpleNamespace) -> None:
    headers = _log_in(site)

    for path in ("/", "/bans/1"):
        response = await site.client.get(path, headers=headers)
        assert response.status == 200
        assert "Ban logging is not loaded" in await response.text()


@pytest.mark.asyncio
async def test_ban_detail_shows_messages(site: SimpleNamespace) -> None:
    channel = SimpleNamespace(name="general")
    site.guild.get_channel_or_thread.side_effect = lambda channel_id: channel if channel_id == 10 else None
    message = {
        "id": 1,
        "channel_id": 10,
        "author_id": 300000000000000001,
        "created_at": 1_700_000_000.0,
        "content": "first version",
        "edited_content": "second version",
        "edited_at": 1_700_000_060.0,
        "deleted_at": 1_700_000_100.0,
        "attachments": ["cat.png"],
    }
    other = {**message, "id": 2, "channel_id": 99, "edited_content": None, "deleted_at": None, "attachments": []}
    banlog = _FakeBanLog()
    banlog.records[7] = {**_ban(7), "messages": [message, other]}
    site.bot.get_cog.return_value = banlog

    body = await (await site.client.get("/bans/7", headers=_log_in(site))).text()

    assert "#general" in body and ">99<" in body
    assert "first version" in body and "second version" in body
    assert "cat.png" in body
    assert body.count("Deleted before ban") == 1


@pytest.mark.asyncio
async def test_unknown_ban_is_404(site: SimpleNamespace) -> None:
    site.bot.get_cog.return_value = _FakeBanLog()

    response = await site.client.get("/bans/404", headers=_log_in(site))

    assert response.status == 404
