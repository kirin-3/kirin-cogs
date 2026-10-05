"""The staff site's role shop page. The Unicornia cog is a fake here; its own tests cover the rules."""

import secrets
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import aiohttp
import discord
import pytest

from dashboard.dashboard import SESSION_COOKIE, Session
from dashboard.tests import test_member_site
from dashboard.tests.test_member_site import CSRF, REGULAR, STAFF, _role

ms = test_member_site.ms  # the member site's fixture, reused

ROLE_ID = 1319776542099767316
CHANNEL_ID = 768087418510639144


class _FakeUnicornia:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.may = True
        self.refuse: Exception | None = None
        self.overview = {
            "channel": {"id": CHANNEL_ID, "name": "role-shop"},
            "channels": [{"id": CHANNEL_ID, "name": "role-shop"}],
            "sections": [
                {
                    "id": 1,
                    "name": "Color roles",
                    "note": "<b>Pick</b> one",
                    "banner": True,
                    "full": False,
                    "url": "https://discord.com/channels/1/2/3",
                    "items": [
                        {
                            "id": 7,
                            "index": 4,
                            "name": "Pink",
                            "price": 14000,
                            "type": "Role",
                            "role_id": 11,
                            "role": "<i>Pink</i>",
                            "requirement_id": None,
                            "requirement": "",
                            "section_id": 1,
                            "problem": None,
                        }
                    ],
                },
                {"id": 2, "name": "Special", "note": "", "banner": False, "full": False, "url": "", "items": []},
            ],
            "items": [
                {
                    "id": 7,
                    "index": 4,
                    "name": "Pink",
                    "price": 14000,
                    "type": "Role",
                    "role_id": 11,
                    "role": "<i>Pink</i>",
                    "requirement_id": None,
                    "requirement": "",
                    "section_id": 1,
                    "problem": None,
                },
                {
                    "id": 8,
                    "index": 5,
                    "name": "Gone",
                    "price": 0,
                    "type": "Role",
                    "role_id": None,
                    "role": "",
                    "requirement_id": None,
                    "requirement": "",
                    "section_id": None,
                    "problem": "Its role was deleted.",
                },
            ],
            "roles": [{"id": ROLE_ID, "name": "Blue"}],
            "requirements": [{"id": ROLE_ID, "name": "Blue"}],
            "may_manage": True,
        }

    async def shop_overview(self, guild: Any, editor: Any) -> dict[str, Any]:
        return {**self.overview, "may_manage": self.may}

    async def shop_may_manage(self, member: Any) -> bool:
        return self.may

    async def _record(self, *call: Any) -> None:
        if self.refuse:
            raise self.refuse
        self.calls.append(call)

    async def shop_post(self, guild: Any, channel: Any) -> None:
        await self._record("post", channel.id)

    async def shop_section_create(self, guild: Any, name: str, note: str) -> None:
        await self._record("create", name, note)

    async def shop_section_edit(self, guild: Any, section_id: int, name: str, note: str) -> None:
        await self._record("edit", section_id, name, note)

    async def shop_section_banner(self, guild: Any, section_id: int, data: bytes | None) -> None:
        await self._record("banner", section_id, data if data is None else len(data))

    async def shop_section_delete(self, guild: Any, section_id: int) -> None:
        await self._record("delete", section_id)

    async def shop_item_add(self, guild: Any, editor: Any, *args: Any) -> None:
        await self._record("add", editor.id, *[getattr(a, "id", a) for a in args])

    async def shop_item_edit(self, guild: Any, editor: Any, item_id: int, *args: Any) -> None:
        await self._record("item", item_id, *[getattr(a, "id", a) for a in args])

    async def shop_item_delete(self, guild: Any, item_id: int) -> None:
        await self._record("remove", item_id)

    async def shop_section_move(self, guild: Any, section_id: int, step: int) -> None:
        await self._record("move", section_id, step)

    async def shop_item_move(self, guild: Any, section_id: int, item_id: int, step: int) -> None:
        await self._record("move item", section_id, item_id, step)


@pytest.fixture
def uni(ms: SimpleNamespace) -> _FakeUnicornia:
    fake = _FakeUnicornia()
    ms.cogs["Unicornia"] = fake
    role, known = _role(ROLE_ID), ms.guild.get_role.side_effect
    ms.guild.get_role.side_effect = lambda role_id: role if role_id == ROLE_ID else known(role_id)
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = CHANNEL_ID
    ms.guild.get_channel.side_effect = lambda channel_id: channel if channel_id == CHANNEL_ID else None
    return fake


def _staff(ms: SimpleNamespace, user_id: int = STAFF) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    ms.cog.sessions[token] = Session(user_id, CSRF, time.monotonic() + 3600)
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


async def _post(ms: SimpleNamespace, path: str, data: dict[str, str] | aiohttp.FormData | None = None):
    if isinstance(data, aiohttp.FormData):
        data.add_field("csrf", CSRF)
    else:
        data = {"csrf": CSRF, **(data or {})}
    return await ms.staff.post(path, data=data, headers=_staff(ms), allow_redirects=False)


@pytest.mark.asyncio
async def test_staff_see_the_channel_sections_and_items(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:
    response = await ms.staff.get("/shop", headers=_staff(ms))
    page = await response.text()

    assert response.status == 200
    assert "Posted in #role-shop." in page and 'id="section-1"' in page and 'id="section-2"' in page
    assert "&lt;i&gt;Pink&lt;/i&gt;" in page and "&lt;b&gt;Pick&lt;/b&gt; one" in page  # escaped
    assert "14,000" in page and "Its role was deleted." in page
    assert 'action="/shop/items/7"' in page and 'action="/shop/sections/1/banner"' in page
    assert f'<option value="{ROLE_ID}">Blue</option>' in page
    assert 'href="/shop" class="on">Role shop</a>' in page


@pytest.mark.asyncio
async def test_staff_without_the_shop_gate_only_look(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:
    uni.may = False

    page = await (await ms.staff.get("/shop", headers=_staff(ms))).text()
    refused = await _post(ms, "/shop/sections", {"name": "Colors"})

    assert "changing the shop needs Manage Roles" in page and 'action="/shop/items/7"' not in page
    assert refused.status == 403 and not uni.calls


@pytest.mark.asyncio
async def test_sections_are_created_edited_and_deleted(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:
    created = await _post(ms, "/shop/sections", {"name": "Colors", "note": "*Pretty*"})
    edited = await _post(ms, "/shop/sections/2", {"name": "Special", "note": ""})
    deleted = await _post(ms, "/shop/sections/2/delete")

    assert (created.status, created.headers["Location"]) == (302, "/shop#new-section")
    assert (edited.status, edited.headers["Location"]) == (302, "/shop#section-2")
    assert deleted.status == 302
    assert uni.calls == [("create", "Colors", "*Pretty*"), ("edit", 2, "Special", ""), ("delete", 2)]


@pytest.mark.asyncio
async def test_banners_upload_up_to_8_mb_and_can_be_removed(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:
    form = aiohttp.FormData()
    form.add_field("banner", b"\x89PNG" + b"x" * (8 * 1024 * 1024 - 4), filename="b.png")
    uploaded = await _post(ms, "/shop/sections/1/banner", form)
    removed = await _post(ms, "/shop/sections/1/banner", {"remove": "1"})
    nothing = await _post(ms, "/shop/sections/1/banner")

    assert uploaded.status == 302 and removed.status == 302
    assert nothing.status == 400 and "Choose an image to upload." in await nothing.text()
    assert uni.calls == [("banner", 1, 8 * 1024 * 1024), ("banner", 1, None)]


@pytest.mark.asyncio
async def test_items_are_added_edited_and_removed(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:
    form = {"name": "Blue", "price": "14000", "role": str(ROLE_ID), "requirement": "", "section": "1"}
    added = await _post(ms, "/shop/items", form)
    edited = await _post(
        ms, "/shop/items/7", {"name": "Pink", "price": "9000", "role": "", "requirement": str(ROLE_ID)}
    )
    removed = await _post(ms, "/shop/items/7/delete")

    assert (added.status, added.headers["Location"]) == (302, "/shop#items")
    assert edited.status == 302 and removed.status == 302
    assert uni.calls == [
        ("add", STAFF, "Blue", 14000, ROLE_ID, None, 1),
        ("item", 7, "Pink", 9000, None, ROLE_ID, None),
        ("remove", 7),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("price", ["", "-1", "1.5", "abc", "9" * 14, chr(0xFF11)])
async def test_a_bad_price_or_missing_role_is_refused(ms: SimpleNamespace, uni: _FakeUnicornia, price: str) -> None:
    bad_price = await _post(ms, "/shop/items", {"name": "Blue", "price": price, "role": str(ROLE_ID)})
    no_role = await _post(ms, "/shop/items", {"name": "Blue", "price": "5", "role": "999"})
    bad_edit = await _post(ms, "/shop/items/7", {"name": "Pink", "price": price})

    assert bad_price.status == no_role.status == bad_edit.status == 400
    assert "Choose a role and a price of 0 or more." in await no_role.text()
    assert not uni.calls


@pytest.mark.asyncio
async def test_a_refused_change_shows_why_where_it_happened(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:
    uni.refuse = ValueError("<b>Mod</b> has moderator permissions.")
    refused = await _post(ms, "/shop/sections/2", {"name": "x", "note": ""})
    page = await refused.text()
    uni.refuse = LookupError("That section doesn't exist anymore.")
    missing = await _post(ms, "/shop/sections/9/delete")

    assert refused.status == 400
    assert '<p class="notice">&lt;b&gt;Mod&lt;/b&gt; has moderator permissions.</p>' in page
    assert page.index('id="section-2"') < page.index('class="notice"')
    assert missing.status == 404


@pytest.mark.asyncio
async def test_posting_needs_a_channel_the_guild_has(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:
    posted = await _post(ms, "/shop/post", {"channel": str(CHANNEL_ID)})
    unknown = await _post(ms, "/shop/post", {"channel": "123"})

    assert (posted.status, posted.headers["Location"]) == (302, "/shop#channel")
    assert unknown.status == 400 and "Choose a channel to post in." in await unknown.text()
    assert uni.calls == [("post", CHANNEL_ID)]


@pytest.mark.asyncio
async def test_the_page_needs_unicornia_and_a_staff_session(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:
    viewed = await ms.staff.get("/shop", headers=_staff(ms, REGULAR), allow_redirects=False)
    no_token = await ms.staff.post("/shop/sections", data={"name": "x"}, headers=_staff(ms), allow_redirects=False)
    del ms.cogs["Unicornia"]
    page = await ms.staff.get("/shop", headers=_staff(ms))

    assert (viewed.status, viewed.headers["Location"]) == (302, "/logged-out")
    assert no_token.status == 403 and page.status == 503 and not uni.calls


@pytest.mark.asyncio
async def test_sections_and_items_move_up_and_down(ms: SimpleNamespace, uni: _FakeUnicornia) -> None:
    page = await (await ms.staff.get("/shop", headers=_staff(ms))).text()
    up = await _post(ms, "/shop/sections/2/move", {"direction": "up"})
    down = await _post(ms, "/shop/sections/1/items/7/move", {"direction": "down"})
    sideways = await _post(ms, "/shop/sections/1/move", {"direction": "left"})

    assert 'action="/shop/sections/1/move"' in page and 'action="/shop/sections/1/items/7/move"' in page
    assert 'aria-label="Move Color roles up" disabled' in page  # the first section can't go higher
    assert 'aria-label="Move Special down" disabled' in page
    assert (up.status, up.headers["Location"]) == (302, "/shop#section-2")
    assert (down.status, down.headers["Location"]) == (302, "/shop#section-1")
    assert sideways.status == 400 and "Choose up or down." in await sideways.text()
    assert uni.calls == [("move", 2, -1), ("move item", 1, 7, 1)]
