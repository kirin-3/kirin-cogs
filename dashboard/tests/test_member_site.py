"""Tests for the member site, my.unicornia.net: both listeners, the shared login throttle, member sessions, and pages."""

import re
import secrets
import socket
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import discord
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from redbot.core.errors import CogLoadError
from yarl import URL

import dashboard.dashboard as dashboard_module
from customemoji.customemoji import CustomEmoji
from customrolecolor.customrolecolor import CustomRoleColor
from dashboard.dashboard import (
    MEMBER_COOKIE,
    MEMBER_SECURITY_HEADERS,
    PUBLIC_PATHS,
    SECURITY_HEADERS,
    SESSION_COOKIE,
    STAFF_ROLE_ID,
    Dashboard,
    Session,
)
from dashboard.member import ACTIVE_SUPPORTER, INACTIVE_SUPPORTER
from dashboard.tests.test_dashboard import _callback, _FakeDiscord, _FakeResponse, _free_port
from roleplay.main import Roleplay

REGULAR, ACTIVE, INACTIVE, STAFF = 300000000000000001, 300000000000000002, 300000000000000003, 300000000000000004
CUSTOM_ROLE_ID = 555
CSRF = "csrf-token"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 100


def _acm(backing: dict) -> object:
    """Awaitable and async-with-able, like a Red Config value."""

    class Value:
        def __await__(self):
            async def read() -> dict:
                return backing

            return read().__await__()

        async def __aenter__(self) -> dict:
            return backing

        async def __aexit__(self, *exc: object) -> None:
            return None

    return Value()


class _FakeCustomCommand:
    """Records the calls the site makes; the rules themselves are tested with the cog."""

    def __init__(self) -> None:
        self.created: list[tuple] = []
        self.deleted: list[tuple] = []
        self.edited: list[tuple] = []
        self.owned: dict[int, list[str]] = {}

    def can_create(self, member: Any) -> bool:
        return any(role.id == ACTIVE_SUPPORTER for role in member.roles)

    async def commands_for(self, member: Any) -> list[dict]:
        return [{"trigger": t, "response": "hi", "attachment": None} for t in self.owned.get(member.id, [])]

    async def limit_for(self, member: Any) -> int:
        return 2

    async def create_command(self, member: Any, trigger: str, response: str, attachment: Any, *, source: str) -> None:
        self.created.append((member.id, trigger, response, attachment, source))

    async def edit_command(
        self, member: Any, old: str, new: str, response: str, attachment: Any, *, remove_file: bool, source: str
    ) -> None:
        if old not in self.owned.get(member.id, []):
            raise ValueError("You don't own a command with that name.")
        self.edited.append((member.id, old, new, response, attachment, remove_file, source))

    async def delete_command(self, member: Any, trigger: str, *, source: str) -> None:
        if trigger not in self.owned.get(member.id, []):
            raise ValueError("You don't own a command with that name.")
        self.deleted.append((member.id, trigger, source))
        self.owned[member.id].remove(trigger)


class _UserConfig:
    """The slice of Red's Config that Roleplay.settings_for/set_toggle use."""

    def __init__(self) -> None:
        self.users: dict[int, dict[str, Any]] = {}

    def user_from_id(self, user_id: int) -> SimpleNamespace:
        data = self.users.setdefault(user_id, {})

        async def all_() -> dict:
            return dict(data)

        def get_attr(key: str) -> SimpleNamespace:
            async def set_(value: Any) -> None:
                data[key] = value

            return SimpleNamespace(set=set_)

        return SimpleNamespace(all=all_, get_attr=get_attr)


def _role(role_id: int, position: int = 10) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.position = position
    role.name = "Sparkles"
    role.managed = False
    role.is_default.return_value = False
    role.mentionable = False
    role.colour = discord.Colour(0x112233)
    role.secondary_colour = None
    role.tertiary_colour = None
    role.display_icon = None
    role.edit = AsyncMock()
    role.__ge__ = lambda self, other: self.position >= other.position
    return role


def _person(guild: MagicMock, user_id: int, roles: list) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.guild = guild
    member.roles = roles
    member.display_name = f"member{user_id % 10}"
    member.get_role.side_effect = lambda role_id: next((r for r in member.roles if r.id == role_id), None)
    member.guild_permissions.ban_members = False
    return member


@pytest_asyncio.fixture
async def ms() -> AsyncIterator[SimpleNamespace]:
    bot = MagicMock()
    bot.application_id = 111
    bot.get_shared_api_tokens = AsyncMock(return_value={"client_secret": "secret"})
    bot.get_user.return_value = None
    bot.is_mod = AsyncMock(return_value=False)

    guild = MagicMock(spec=discord.Guild)
    guild.id = dashboard_module.GUILD_ID
    guild.features = ["ROLE_ICONS"]
    guild.me.guild_permissions.manage_roles = True
    guild.me.top_role = _role(1, position=100)
    active_role, inactive_role = _role(ACTIVE_SUPPORTER), _role(INACTIVE_SUPPORTER)
    custom_role = _role(CUSTOM_ROLE_ID, position=50)
    roles = {r.id: r for r in (active_role, inactive_role, custom_role)}
    guild.get_role.side_effect = roles.get
    emojis: dict[int, MagicMock] = {}
    guild.get_emoji.side_effect = emojis.get
    members = {
        REGULAR: _person(guild, REGULAR, []),
        ACTIVE: _person(guild, ACTIVE, [active_role]),
        INACTIVE: _person(guild, INACTIVE, [inactive_role]),
        STAFF: _person(guild, STAFF, [SimpleNamespace(id=STAFF_ROLE_ID)]),
    }
    guild.get_member.side_effect = members.get
    bot.get_guild.return_value = guild

    ce_group = MagicMock()
    ce_group.required_role_id = AsyncMock(return_value=ACTIVE_SUPPORTER)
    ce_group.user_limits = AsyncMock(return_value={})
    ownership: dict[str, int] = {}
    ce_group.emoji_ownership = MagicMock(side_effect=lambda: _acm(ownership))
    with patch("customemoji.customemoji.Config.get_conf", return_value=MagicMock(guild=lambda _: ce_group)):
        ce = CustomEmoji(bot)

    assignments: dict[str, int] = {}
    crc_group = MagicMock()
    crc_group.assignments = AsyncMock(side_effect=lambda: dict(assignments))
    with patch("customrolecolor.customrolecolor.Config.get_conf", return_value=MagicMock(guild=lambda _: crc_group)):
        crc = CustomRoleColor(bot)

    rp_config = _UserConfig()
    rp = SimpleNamespace(user_settings=SimpleNamespace(config=rp_config))
    rp.settings_for = lambda user_id: Roleplay.settings_for(rp, user_id)  # type: ignore[arg-type]
    rp.set_toggle = lambda user_id, key, value: Roleplay.set_toggle(rp, user_id, key, value)  # type: ignore[arg-type]

    cc = _FakeCustomCommand()
    cogs: dict[str, Any] = {"CustomCommand": cc, "CustomEmoji": ce, "CustomRoleColor": crc, "Roleplay": rp}
    bot.get_cog.side_effect = cogs.get

    cog = Dashboard(bot)
    fake_discord = _FakeDiscord()
    cog._http = fake_discord  # type: ignore[assignment]
    client = TestClient(TestServer(cog.make_member_app()))
    staff = TestClient(TestServer(cog.make_app()))
    await client.start_server()
    await staff.start_server()
    yield SimpleNamespace(
        cog=cog,
        bot=bot,
        guild=guild,
        members=members,
        client=client,
        staff=staff,
        discord=fake_discord,
        cogs=cogs,
        cc=cc,
        ce=ce,
        ce_group=ce_group,
        ownership=ownership,
        emojis=emojis,
        assignments=assignments,
        custom_role=custom_role,
        active_role=active_role,
        rp_users=rp_config.users,
    )
    await client.close()
    await staff.close()


def _log_in(ms: SimpleNamespace, user_id: int) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    ms.cog.member_sessions[token] = Session(user_id, CSRF, time.monotonic() + 3600)
    return {"Cookie": f"{MEMBER_COOKIE}={token}"}


async def _post(ms: SimpleNamespace, user_id: int, path: str, data: dict | aiohttp.FormData | None = None, **kw: Any):
    if isinstance(data, aiohttp.FormData):
        data.add_field("csrf", CSRF)
    else:
        data = {"csrf": CSRF, **(data or {})}
    return await ms.client.post(path, data=data, headers=_log_in(ms, user_id), allow_redirects=False, **kw)


async def _get(ms: SimpleNamespace, user_id: int, path: str) -> tuple[int, str]:
    response = await ms.client.get(path, headers=_log_in(ms, user_id), allow_redirects=False)
    return response.status, await response.text()


def _upload(field: str, data: bytes, filename: str, **fields: str) -> aiohttp.FormData:
    form = aiohttp.FormData()
    for name, value in fields.items():
        form.add_field(name, value)
    form.add_field(field, data, filename=filename, content_type="application/octet-stream")
    return form


async def _member_callback(ms: SimpleNamespace, **kwargs: Any) -> aiohttp.ClientResponse:
    return await _callback(SimpleNamespace(client=ms.client), **kwargs)


# --- listeners -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_sites_listen_on_loopback_until_unloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    staff_port, member_port = _free_port(), _free_port()
    monkeypatch.setattr(dashboard_module, "STAFF_PORT", staff_port)
    monkeypatch.setattr(dashboard_module, "MEMBER_PORT", member_port)
    cog = Dashboard(MagicMock())
    await cog.cog_load()
    async with aiohttp.ClientSession() as http:
        for port, title in ((staff_port, "Staff login"), (member_port, "Member login")):
            async with http.get(f"http://127.0.0.1:{port}/logged-out") as response:
                assert response.status == 200 and title in await response.text()

        await cog.cog_unload()

        for port in (staff_port, member_port):
            with pytest.raises(aiohttp.ClientConnectorError):
                await http.get(f"http://127.0.0.1:{port}/logged-out")


@pytest.mark.asyncio
async def test_member_port_in_use_fails_the_load_and_leaves_nothing_running(monkeypatch: pytest.MonkeyPatch) -> None:
    staff_port = _free_port()
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        member_port = blocker.getsockname()[1]
        monkeypatch.setattr(dashboard_module, "STAFF_PORT", staff_port)
        monkeypatch.setattr(dashboard_module, "MEMBER_PORT", member_port)
        cog = Dashboard(MagicMock())

        with pytest.raises(CogLoadError, match=f"member site .*{member_port}"):
            await cog.cog_load()

    assert cog._runner.server is None and cog._member_runner.server is None
    async with aiohttp.ClientSession() as http:
        with pytest.raises(aiohttp.ClientConnectorError):
            await http.get(f"http://127.0.0.1:{staff_port}/logged-out")


# --- login ---------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_login_uses_the_member_callback(ms: SimpleNamespace) -> None:
    response = await ms.client.get("/login", allow_redirects=False)

    assert URL(response.headers["Location"]).query["redirect_uri"] == "https://my.unicornia.net/callback"


@pytest.mark.asyncio
async def test_member_without_2fa_gets_a_member_session(ms: SimpleNamespace) -> None:
    ms.discord.me = _FakeResponse(200, {"id": str(REGULAR), "mfa_enabled": False})

    response = await _member_callback(ms)

    assert response.status == 302 and response.headers["Location"] == "/"
    [(token, session)] = ms.cog.member_sessions.items()
    assert session.user_id == REGULAR and ms.cog.sessions == {}
    assert response.cookies[MEMBER_COOKIE].value == token
    home = await ms.client.get("/", headers={"Cookie": f"{MEMBER_COOKIE}={token}"})
    assert home.status == 200


@pytest.mark.asyncio
async def test_non_member_is_refused(ms: SimpleNamespace) -> None:
    ms.discord.me = _FakeResponse(200, {"id": "999", "mfa_enabled": True})

    response = await _member_callback(ms)

    assert response.status == 403 and "Members only" in await response.text()
    assert ms.cog.member_sessions == {}


@pytest.mark.asyncio
async def test_member_who_left_is_logged_out(ms: SimpleNamespace) -> None:
    headers = _log_in(ms, REGULAR)
    del ms.members[REGULAR]

    response = await ms.client.get("/roleplay", headers=headers, allow_redirects=False)

    assert response.headers["Location"] == "/logged-out"
    assert ms.cog.member_sessions == {}


@pytest.mark.asyncio
async def test_sessions_do_not_cross_sites(ms: SimpleNamespace) -> None:
    staff_token = secrets.token_urlsafe(32)
    ms.cog.sessions[staff_token] = Session(STAFF, CSRF, time.monotonic() + 3600)
    member_token = _log_in(ms, STAFF)["Cookie"].split("=", 1)[1]

    for cookie in (f"{SESSION_COOKIE}={staff_token}", f"{MEMBER_COOKIE}={staff_token}"):
        response = await ms.client.get("/", headers={"Cookie": cookie}, allow_redirects=False)
        assert response.headers["Location"] == "/logged-out", cookie
    for cookie in (f"{SESSION_COOKIE}={member_token}", f"{MEMBER_COOKIE}={member_token}"):
        response = await ms.staff.get("/", headers={"Cookie": cookie}, allow_redirects=False)
        assert response.headers["Location"] == "/logged-out", cookie


# --- shared throttle -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_logins_leave_ten_exchanges_for_staff(ms: SimpleNamespace) -> None:
    ms.discord.token = _FakeResponse(400)
    for n in range(20):
        await _member_callback(ms, ip=f"198.51.100.{n}")

    member = await _member_callback(ms, ip="192.0.2.1")
    staff = await _callback(SimpleNamespace(client=ms.staff), ip="192.0.2.2")

    assert member.status == 429
    assert staff.status == 400  # reached Discord
    assert len(ms.discord.calls) == 21


@pytest.mark.parametrize("first", ["member", "staff"])
@pytest.mark.asyncio
async def test_discord_429_on_either_site_pauses_both(ms: SimpleNamespace, first: str) -> None:
    ms.discord.token = _FakeResponse(429, None, {"Retry-After": "30"})
    clients = {"member": ms.client, "staff": ms.staff}
    await _callback(SimpleNamespace(client=clients[first]))

    for name, client in clients.items():
        response = await _callback(SimpleNamespace(client=client), ip="192.0.2.50")
        assert response.status == 429, name
    assert len(ms.discord.calls) == 1


# --- routing and hardening -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_member_route_rejects_anonymous_visitors(ms: SimpleNamespace) -> None:
    checked = 0
    for route in ms.client.app.router.routes():
        resource = route.resource
        if resource is None or isinstance(resource, web.StaticResource) or resource.canonical in PUBLIC_PATHS:
            continue
        path = re.sub(r"\{[^}]+\}", "1", resource.canonical)
        response = await ms.client.request(route.method, path, allow_redirects=False)
        if route.method in ("GET", "HEAD"):
            assert (response.status, response.headers["Location"]) == (302, "/logged-out"), path
        else:
            assert response.status == 401, path
        checked += 1
    assert checked >= 20


@pytest.mark.asyncio
async def test_every_member_post_needs_the_csrf_token(ms: SimpleNamespace) -> None:
    for route in ms.client.app.router.routes():
        if route.method != "POST":
            continue
        path = re.sub(r"\{[^}]+\}", "1", route.resource.canonical)  # type: ignore[union-attr]
        response = await ms.client.post(path, data={}, headers=_log_in(ms, ACTIVE), allow_redirects=False)
        assert response.status == 403, path
    assert ms.cc.created == [] and ms.cc.deleted == []


@pytest.mark.asyncio
async def test_bodies_over_9_mb_are_refused(ms: SimpleNamespace) -> None:
    form = _upload("file", b"x" * (10 * 1024 * 1024), "big.bin", trigger="big")

    response = await _post(ms, ACTIVE, "/commands", form)

    assert response.status == 413
    assert ms.cc.created == []


@pytest.mark.parametrize("path", ["/automod", "/bans/1", "/automod/log"])
@pytest.mark.asyncio
async def test_staff_pages_are_not_on_the_member_site(ms: SimpleNamespace, path: str) -> None:
    status, _ = await _get(ms, STAFF, path)

    assert status == 404


@pytest.mark.asyncio
async def test_member_pages_may_show_discord_images_and_nothing_else_changes(ms: SimpleNamespace) -> None:
    response = await ms.client.get("/", headers=_log_in(ms, REGULAR))
    staff = await ms.staff.get("/logged-out")

    for name, value in MEMBER_SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert (
        "img-src 'self' https://cdn.discordapp.com https://unicornia.net;"
        in response.headers["Content-Security-Policy"]
    )
    assert staff.headers["Content-Security-Policy"] == SECURITY_HEADERS["Content-Security-Policy"]


# --- navigation ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigation_follows_the_members_roles(ms: SimpleNamespace) -> None:
    _, regular = await _get(ms, REGULAR, "/")
    _, active = await _get(ms, ACTIVE, "/")
    ms.custom_role.id = CUSTOM_ROLE_ID
    ms.members[INACTIVE].roles.append(ms.custom_role)
    ms.assignments[str(INACTIVE)] = CUSTOM_ROLE_ID
    _, with_role = await _get(ms, INACTIVE, "/")

    assert 'href="/roleplay"' in regular and 'href="/commands"' not in regular and 'href="/role"' not in regular
    assert 'href="/commands"' in active and 'href="/emojis"' in active and 'href="/role"' not in active
    assert 'href="/role"' in with_role


@pytest.mark.asyncio
async def test_legacy_supporters_see_only_the_sections_they_have_items_in(ms: SimpleNamespace) -> None:
    _, nothing = await _get(ms, INACTIVE, "/")
    statuses = [(await _get(ms, INACTIVE, path))[0] for path in ("/commands", "/emojis")]
    ms.cc.owned[INACTIVE] = ["mine"]
    _, with_command = await _get(ms, INACTIVE, "/")
    ms.emojis[777] = MagicMock(spec=discord.Emoji, id=777)
    ms.ownership["777"] = INACTIVE
    _, with_both = await _get(ms, INACTIVE, "/")

    assert 'href="/commands"' not in nothing and 'href="/emojis"' not in nothing
    assert statuses == [403, 403]
    assert 'href="/commands"' in with_command and 'href="/emojis"' not in with_command
    assert 'href="/commands"' in with_both and 'href="/emojis"' in with_both


@pytest.mark.parametrize("path", ["/commands", "/emojis", "/role"])
@pytest.mark.asyncio
async def test_regular_members_get_403_on_supporter_pages(ms: SimpleNamespace, path: str) -> None:
    status, _ = await _get(ms, REGULAR, path)

    assert status == 403


@pytest.mark.asyncio
async def test_losing_the_supporter_role_mid_session_refuses_the_page(ms: SimpleNamespace) -> None:
    ms.cc.owned[INACTIVE] = ["mine"]
    headers = _log_in(ms, INACTIVE)
    assert (await ms.client.get("/commands", headers=headers)).status == 200

    ms.members[INACTIVE].roles.clear()
    response = await ms.client.get("/commands", headers=headers)

    assert response.status == 403 and 'href="/commands"' not in await response.text()


# --- custom commands -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_supporter_creates_a_command_with_a_file(ms: SimpleNamespace) -> None:
    data = b"\x89PNG" + b"x" * (1024 * 1024)
    form = _upload("file", data, "cat.png", trigger="hello there", response="Hi!")

    response = await _post(ms, ACTIVE, "/commands", form)

    assert response.status == 302 and response.headers["Location"] == "/commands"
    assert ms.cc.created == [(ACTIVE, "hello there", "Hi!", ("cat.png", data), "web")]


@pytest.mark.asyncio
async def test_empty_file_field_creates_without_a_file(ms: SimpleNamespace) -> None:
    response = await _post(ms, ACTIVE, "/commands", _upload("file", b"", "", trigger="hi", response="there"))

    assert response.status == 302
    assert ms.cc.created == [(ACTIVE, "hi", "there", None, "web")]


@pytest.mark.asyncio
async def test_inactive_supporter_cannot_create_commands(ms: SimpleNamespace) -> None:
    ms.cc.owned[INACTIVE] = ["mine"]
    status, page = await _get(ms, INACTIVE, "/commands")
    _, active_page = await _get(ms, ACTIVE, "/commands")
    response = await _post(ms, INACTIVE, "/commands", {"trigger": "hi", "response": "there"})

    assert status == 200 and "New command" not in page
    assert "Only active supporters can create new commands or edit existing ones." in page
    assert "Only active supporters" not in active_page
    assert response.status == 403
    assert ms.cc.created == []


@pytest.mark.asyncio
async def test_deleting_someone_elses_command_shows_the_error(ms: SimpleNamespace) -> None:
    ms.cc.owned[INACTIVE] = ["mine"]

    refused = await _post(ms, INACTIVE, "/commands/delete", {"trigger": "theirs"})
    done = await _post(ms, INACTIVE, "/commands/delete", {"trigger": "mine"})

    assert refused.status == 400 and "You don&#39;t own a command with that name." in await refused.text()
    assert done.status == 302 and done.headers["Location"] == "/"  # that was their last command
    assert ms.cc.deleted == [(INACTIVE, "mine", "web")]


# --- custom emojis -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_png_upload_creates_an_emoji(ms: SimpleNamespace) -> None:
    created = MagicMock(spec=discord.Emoji, id=777)
    created.name = "party_cat"
    ms.guild.create_custom_emoji = AsyncMock(return_value=created)

    response = await _post(ms, ACTIVE, "/emojis", _upload("image", PNG, "party_cat.png", name="party_cat"))

    assert response.status == 302
    assert ms.guild.create_custom_emoji.await_args_list[0].kwargs["name"] == "party_cat"
    assert ms.ownership == {"777": ACTIVE}


@pytest.mark.asyncio
async def test_text_file_renamed_to_png_is_refused(ms: SimpleNamespace) -> None:
    ms.guild.create_custom_emoji = AsyncMock()

    response = await _post(ms, ACTIVE, "/emojis", _upload("image", b"hello, world", "cat.png", name="cat"))

    assert response.status == 400 and "must be a PNG, JPEG or GIF" in await response.text()
    ms.guild.create_custom_emoji.assert_not_awaited()


@pytest.mark.asyncio
async def test_emoji_page_lists_own_emojis_with_cdn_previews(ms: SimpleNamespace) -> None:
    emoji = MagicMock(spec=discord.Emoji, id=777, url="https://cdn.discordapp.com/emojis/777.png")
    emoji.name = "party_cat"
    ms.emojis[777] = emoji
    ms.ownership["777"] = INACTIVE

    status, page = await _get(ms, INACTIVE, "/emojis")

    assert status == 200
    assert 'src="https://cdn.discordapp.com/emojis/777.png"' in page and ":party_cat:" in page
    assert "1 of 2 slots used" in page
    assert "Rename" not in page and "New emoji" not in page
    assert "Only active supporters can create new emojis or rename existing ones." in page


@pytest.mark.asyncio
async def test_inactive_supporter_cannot_rename_but_can_delete(ms: SimpleNamespace) -> None:
    emoji = MagicMock(spec=discord.Emoji, id=777)
    emoji.name = "party_cat"
    emoji.edit, emoji.delete = AsyncMock(), AsyncMock()
    ms.emojis[777] = emoji
    ms.ownership["777"] = INACTIVE

    renamed = await _post(ms, INACTIVE, "/emojis/777/rename", {"name": "new_name"})
    deleted = await _post(ms, INACTIVE, "/emojis/777/delete")

    assert renamed.status == 403
    emoji.edit.assert_not_awaited()
    assert deleted.status == 302 and deleted.headers["Location"] == "/"
    emoji.delete.assert_awaited_once()
    assert ms.ownership == {}


# --- custom role ---------------------------------------------------------------------------------


def _give_role(ms: SimpleNamespace, user_id: int) -> MagicMock:
    ms.members[user_id].roles.append(ms.custom_role)
    ms.assignments[str(user_id)] = CUSTOM_ROLE_ID
    return ms.custom_role


@pytest.mark.asyncio
async def test_role_page_shows_colors_as_swatches(ms: SimpleNamespace) -> None:
    _give_role(ms, INACTIVE)

    status, page = await _get(ms, INACTIVE, "/role")

    assert status == 200
    assert '<input type="color" value="#112233" disabled' in page
    assert "Sparkles" in page and 'action="/role/icon"' in page
    # site.js reads the saved colors from here for the live preview
    assert '<div class="role-preview" data-colors="112233"' in page
    assert 'data-colors="a9c9ff ffbbec ffc3a0"' in page  # the holographic preset, for its hover preview


@pytest.mark.asyncio
async def test_gradient_updates_both_colors(ms: SimpleNamespace) -> None:
    role = _give_role(ms, INACTIVE)

    response = await _post(ms, INACTIVE, "/role/color", {"primary": "#ff0000", "secondary": "#0000ff", "gradient": "1"})

    assert response.status == 302
    changes = role.edit.await_args_list[0].kwargs
    assert changes["colour"] == discord.Colour(0xFF0000) and changes["secondary_colour"] == discord.Colour(0x0000FF)


@pytest.mark.asyncio
async def test_role_above_the_bot_is_refused_with_the_reason(ms: SimpleNamespace) -> None:
    role = _give_role(ms, ACTIVE)
    role.position = 200

    status, page = await _get(ms, ACTIVE, "/role")
    response = await _post(ms, ACTIVE, "/role/name", {"name": "New name"})

    assert "higher than or equal to my top role" in page and status == 200
    assert response.status == 400 and "higher than or equal to my top role" in await response.text()
    role.edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_supporter_without_an_assignment_gets_403(ms: SimpleNamespace) -> None:
    status, _ = await _get(ms, ACTIVE, "/role")
    response = await _post(ms, ACTIVE, "/role/name", {"name": "Mine now"})

    assert status == 403 and response.status == 403
    ms.custom_role.edit.assert_not_awaited()


# --- roleplay ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turning_public_on_persists(ms: SimpleNamespace) -> None:
    response = await _post(ms, REGULAR, "/roleplay", {"key": "public", "value": "on"})
    _, page = await _get(ms, REGULAR, "/roleplay")

    assert response.status == 302
    assert ms.rp_users[REGULAR]["public"] is True
    assert "Turn off" in page


@pytest.mark.parametrize(
    "form", [{"key": "owners", "value": "on"}, {"key": "allowed", "value": "on"}, {"key": "public", "value": "maybe"}]
)
@pytest.mark.asyncio
async def test_roleplay_lists_cannot_be_changed(ms: SimpleNamespace, form: dict) -> None:
    response = await _post(ms, REGULAR, "/roleplay", form)

    assert response.status == 400
    assert ms.rp_users.get(REGULAR, {}) == {}


@pytest.mark.asyncio
async def test_roleplay_page_shows_toggles_and_lists_by_name(ms: SimpleNamespace) -> None:
    ms.rp_users[REGULAR] = {"selective": True, "allowed": [ACTIVE, 42]}

    _, page = await _get(ms, REGULAR, "/roleplay")

    assert "Selective" in page and "member2" in page and "Unknown user" in page
    assert 'name="key" value="allowed"' not in page


@pytest.mark.asyncio
async def test_roleplay_page_explains_when_the_cog_is_unloaded(ms: SimpleNamespace) -> None:
    del ms.cogs["Roleplay"]

    status, page = await _get(ms, REGULAR, "/roleplay")

    assert status == 200 and "Roleplay settings are unavailable" in page


# --- settings ------------------------------------------------------------------------------------


class _FakeResponder:
    """Responder's settings_for/set_toggle; the real ones are tested with the cog."""

    def __init__(self) -> None:
        self.daddy: dict[int, bool] = {}

    async def settings_for(self, user_id: int) -> dict[str, dict]:
        item = {"label": "Daddy replies", "description": "Hi, I'm your daddy", "emoji": "👨"}
        return {"daddy": {**item, "value": self.daddy.get(user_id, True)}}

    async def set_toggle(self, user_id: int, key: str, value: bool) -> None:
        if key != "daddy":
            raise ValueError(key)
        self.daddy[user_id] = value


@pytest.mark.asyncio
async def test_settings_page_turns_daddy_replies_off_and_on(ms: SimpleNamespace) -> None:
    responder = ms.cogs["ResponderCog"] = _FakeResponder()

    _, home = await _get(ms, REGULAR, "/")
    status, page = await _get(ms, REGULAR, "/settings")
    assert 'href="/settings"' in home
    assert status == 200 and "Daddy replies" in page and "Turn off" in page

    response = await _post(ms, REGULAR, "/settings", {"key": "daddy", "value": "off"})
    _, page = await _get(ms, REGULAR, "/settings")
    assert response.status == 302 and response.headers["Location"] == "/settings"
    assert responder.daddy == {REGULAR: False} and "Turn on" in page

    await _post(ms, REGULAR, "/settings", {"key": "daddy", "value": "on"})
    assert responder.daddy == {REGULAR: True}


@pytest.mark.parametrize("form", [{"key": "nope", "value": "off"}, {"key": "daddy", "value": "maybe"}])
@pytest.mark.asyncio
async def test_settings_rejects_unknown_keys_and_values(ms: SimpleNamespace, form: dict) -> None:
    responder = ms.cogs["ResponderCog"] = _FakeResponder()

    response = await _post(ms, REGULAR, "/settings", form)

    assert response.status == 400 and responder.daddy == {}


@pytest.mark.asyncio
async def test_settings_needs_the_csrf_token(ms: SimpleNamespace) -> None:
    responder = ms.cogs["ResponderCog"] = _FakeResponder()

    response = await ms.client.post(
        "/settings", data={"key": "daddy", "value": "off"}, headers=_log_in(ms, REGULAR), allow_redirects=False
    )

    assert response.status == 403 and responder.daddy == {}


@pytest.mark.asyncio
async def test_settings_page_explains_when_the_cog_is_unloaded(ms: SimpleNamespace) -> None:
    status, page = await _get(ms, REGULAR, "/settings")
    response = await _post(ms, REGULAR, "/settings", {"key": "daddy", "value": "off"})

    assert status == 200 and "Settings are unavailable" in page
    assert response.status == 503


@pytest.mark.asyncio
async def test_active_supporter_edits_a_command(ms: SimpleNamespace) -> None:
    ms.cc.owned[ACTIVE] = ["cat"]
    _, page = await _get(ms, ACTIVE, "/commands")
    form = _upload("file", b"gif", "new.gif", old="cat", trigger="kitty", response="purr", remove_file="1")

    response = await _post(ms, ACTIVE, "/commands/edit", form)

    assert 'action="/commands/edit"' in page and 'name="old" value="cat"' in page
    assert response.status == 302
    assert ms.cc.edited == [(ACTIVE, "cat", "kitty", "purr", ("new.gif", b"gif"), True, "web")]


@pytest.mark.asyncio
async def test_blank_trigger_keeps_the_old_one(ms: SimpleNamespace) -> None:
    ms.cc.owned[ACTIVE] = ["cat"]

    await _post(ms, ACTIVE, "/commands/edit", {"old": "cat", "trigger": "", "response": "purr"})

    assert ms.cc.edited == [(ACTIVE, "cat", "cat", "purr", None, False, "web")]


@pytest.mark.asyncio
async def test_inactive_supporter_cannot_edit_commands(ms: SimpleNamespace) -> None:
    ms.cc.owned[INACTIVE] = ["cat"]
    _, page = await _get(ms, INACTIVE, "/commands")

    response = await _post(ms, INACTIVE, "/commands/edit", {"old": "cat", "trigger": "cat", "response": "purr"})

    assert 'action="/commands/edit"' not in page
    assert response.status == 403 and ms.cc.edited == []


@pytest.mark.asyncio
async def test_editing_someone_elses_command_shows_the_error(ms: SimpleNamespace) -> None:
    response = await _post(ms, ACTIVE, "/commands/edit", {"old": "theirs", "trigger": "mine", "response": "x"})

    assert response.status == 400 and "You don&#39;t own a command with that name." in await response.text()


@pytest.mark.asyncio
async def test_active_supporter_stays_on_the_page_after_deleting_their_last_command(ms: SimpleNamespace) -> None:
    ms.cc.owned[ACTIVE] = ["mine"]

    response = await _post(ms, ACTIVE, "/commands/delete", {"trigger": "mine"})

    assert response.headers["Location"] == "/commands"
