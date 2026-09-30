"""The staff site's self-role page. The SelfRoles cog is a fake here; its own tests cover the rules."""

import secrets
import time
from types import SimpleNamespace
from typing import Any

import pytest

from dashboard.dashboard import SESSION_COOKIE, Session
from dashboard.tests import test_member_site
from dashboard.tests.test_member_site import CSRF, REGULAR, STAFF, _log_in, _role

ms = test_member_site.ms  # the member site's fixture, reused

ROLE_ID = 1319776542099767316  # a real role ID's length: 19 digits


class _FakeSelfRoles:
    def __init__(self) -> None:
        self.added: list[tuple[Any, ...]] = []
        self.removed: list[tuple[int, int]] = []
        self.refuse: str | None = None
        self.categories = [
            {
                "id": 1,
                "name": "Orientation",
                "limit": "Pick up to 3.",
                "roles": [
                    {"id": 11, "name": "Straight", "emoji": "❤️", "problem": None},
                    {"id": 12, "name": "", "emoji": "<:bi:123456789012345678>", "problem": "This role was deleted."},
                ],
                "full": False,
                "channel": "#roles",
                "url": "https://discord.com/channels/1/2/3",
                "choices": [{"id": ROLE_ID, "name": "<b>Gay</b>"}],
            },
            {
                "id": 2,
                "name": "Age",
                "limit": "Pick one.",
                "roles": [],
                "full": False,
                "channel": "",
                "url": "",
                "choices": [],
            },
        ]

    async def overview(self, guild: Any, editor: Any) -> list[dict[str, Any]]:
        assert editor.id == STAFF
        return self.categories

    async def add_role(self, guild: Any, editor: Any, category_id: int, role: Any, emoji: str) -> None:
        if category_id not in (1, 2):
            raise LookupError(category_id)
        if self.refuse:
            raise ValueError(self.refuse)
        self.added.append((editor.id, category_id, role.id, emoji))

    async def remove_role(self, guild: Any, category_id: int, role_id: int) -> None:
        if category_id not in (1, 2):
            raise LookupError(category_id)
        self.removed.append((category_id, role_id))


@pytest.fixture
def sr(ms: SimpleNamespace) -> _FakeSelfRoles:
    fake = _FakeSelfRoles()
    ms.cogs["SelfRoles"] = fake
    role, known = _role(ROLE_ID), ms.guild.get_role.side_effect
    ms.guild.get_role.side_effect = lambda role_id: role if role_id == ROLE_ID else known(role_id)
    return fake


def _staff(ms: SimpleNamespace, user_id: int = STAFF) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    ms.cog.sessions[token] = Session(user_id, CSRF, time.monotonic() + 3600)
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


async def _post(ms: SimpleNamespace, path: str, data: dict[str, str] | None = None, user_id: int = STAFF):
    body = {"csrf": CSRF, **(data or {})}
    return await ms.staff.post(path, data=body, headers=_staff(ms, user_id), allow_redirects=False)


@pytest.mark.asyncio
async def test_staff_see_each_category_with_its_roles_and_what_they_can_add(
    ms: SimpleNamespace, sr: _FakeSelfRoles
) -> None:
    response = await ms.staff.get("/selfroles", headers=_staff(ms))
    page = await response.text()

    assert response.status == 200
    assert 'id="category-1"' in page and "Orientation" in page and "Pick up to 3." in page
    assert '<a href="https://discord.com/channels/1/2/3">Posted in #roles</a>' in page
    assert "Straight" in page and "Deleted role" in page and "Not offered: This role was deleted." in page
    assert 'src="https://cdn.discordapp.com/emojis/123456789012345678.webp"' in page  # custom emoji shown
    assert 'action="/selfroles/1/roles/12/delete"' in page
    assert f'<option value="{ROLE_ID}">&lt;b&gt;Gay&lt;/b&gt;</option>' in page  # escaped
    assert "Not posted yet." in page and "There are no roles you can add" in page  # Age
    assert 'href="/selfroles" class="on">Self roles</a>' in page


@pytest.mark.asyncio
async def test_adding_a_role_hands_it_to_the_cog_and_returns_to_the_category(
    ms: SimpleNamespace, sr: _FakeSelfRoles
) -> None:
    response = await _post(ms, "/selfroles/1/roles", {"role": str(ROLE_ID), "emoji": " :gay: "})

    assert (response.status, response.headers["Location"]) == (302, "/selfroles#category-1")
    assert sr.added == [(STAFF, 1, ROLE_ID, " :gay: ")]


@pytest.mark.asyncio
async def test_a_refused_change_shows_why_under_its_category(ms: SimpleNamespace, sr: _FakeSelfRoles) -> None:
    sr.refuse = "<i>Mod</i> has moderator permissions."

    response = await _post(ms, "/selfroles/2/roles", {"role": str(ROLE_ID)})
    page = await response.text()

    assert response.status == 400
    assert '<p class="notice">&lt;i&gt;Mod&lt;/i&gt; has moderator permissions.</p>' in page
    assert page.index('id="category-2"') < page.index('class="notice"')  # shown in Age, not Orientation
    assert not sr.added


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["", "abc", "999", "13197765420997673160", "1" * 21, "9" * 5000, "\uff11\uff12"])
async def test_a_role_that_does_not_exist_is_refused(ms: SimpleNamespace, sr: _FakeSelfRoles, role: str) -> None:
    response = await _post(ms, "/selfroles/1/roles", {"role": role})

    assert response.status == 400 and "Choose a role to add." in await response.text()
    assert not sr.added


@pytest.mark.asyncio
async def test_removing_a_role_hands_it_to_the_cog(ms: SimpleNamespace, sr: _FakeSelfRoles) -> None:
    response = await _post(ms, "/selfroles/1/roles/12/delete")

    assert (response.status, response.headers["Location"]) == (302, "/selfroles#category-1")
    assert sr.removed == [(1, 12)]


@pytest.mark.asyncio
async def test_an_unknown_category_is_404(ms: SimpleNamespace, sr: _FakeSelfRoles) -> None:
    added = await _post(ms, "/selfroles/7/roles", {"role": str(ROLE_ID)})
    removed = await _post(ms, "/selfroles/7/roles/12/delete")

    assert added.status == 404 and removed.status == 404
    assert not sr.added and not sr.removed


@pytest.mark.asyncio
async def test_the_page_needs_the_cog(ms: SimpleNamespace, sr: _FakeSelfRoles) -> None:
    del ms.cogs["SelfRoles"]

    page = await ms.staff.get("/selfroles", headers=_staff(ms))
    added = await _post(ms, "/selfroles/1/roles", {"role": str(ROLE_ID)})

    assert page.status == 503 and added.status == 503


@pytest.mark.asyncio
async def test_only_staff_with_the_csrf_token_can_change_anything(ms: SimpleNamespace, sr: _FakeSelfRoles) -> None:
    form = {"role": str(ROLE_ID)}
    anonymous = await ms.staff.post("/selfroles/1/roles", data={"csrf": CSRF, **form}, allow_redirects=False)
    member_cookie = await ms.staff.post(
        "/selfroles/1/roles", data={"csrf": CSRF, **form}, headers=_log_in(ms, REGULAR), allow_redirects=False
    )
    not_staff = await _post(ms, "/selfroles/1/roles", form, user_id=REGULAR)
    no_token = await ms.staff.post("/selfroles/1/roles", data=form, headers=_staff(ms), allow_redirects=False)
    viewed = await ms.staff.get("/selfroles", headers=_log_in(ms, REGULAR), allow_redirects=False)

    assert anonymous.status == 401 and member_cookie.status == 401 and not_staff.status == 401
    assert no_token.status == 403
    assert (viewed.status, viewed.headers["Location"]) == (302, "/logged-out")
    assert not sr.added
