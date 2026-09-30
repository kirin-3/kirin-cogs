"""The roleplay gifs on both sites: browsing, voting, sending in a gif, the vote totals, and the headers and request
limits that go with them. The Roleplay cog is a fake here; its own tests cover the rules."""

import re
import secrets
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

import dashboard.dashboard as dashboard_module
from dashboard.dashboard import (
    MEMBER_SECURITY_HEADERS,
    SECURITY_HEADERS,
    SESSION_COOKIE,
    Session,
)
from dashboard.gifs import MAX_PAGE
from dashboard.tests import test_member_site
from dashboard.tests.test_member_site import (
    ACTIVE,
    CSRF,
    INACTIVE,
    REGULAR,
    STAFF,
    _get,
    _log_in,
    _post,
    _unicornia,
    _upload,
)

ms = test_member_site.ms  # the member site's fixture, reused

GIF = b"GIF89a" + b"\0" * 100
POOLS = ("default", "wlw", "mlm")


class _FakeRoleplay:
    """The gif methods of the Roleplay cog, over a made-up folder: bite has 22 gifs and bow 20."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.uploaders = {ACTIVE, INACTIVE}
        self.gifs: dict[tuple[str, str], list[str]] = {}
        self.mine: dict[str, int] = {}
        self.ai: set[str] = set()
        self.pages = 3
        self.page_requests: list[tuple[str, str, int, int]] = []
        self.votes: list[tuple[int, str, str, int]] = []
        self.submitted: list[tuple[int, str, bytes]] = []
        self.files: list[Any] = []
        self.actions_reads = 0
        self.refuse: str | None = None
        self.totals: list[dict] = []

    def can_submit_gif(self, member: Any) -> bool:
        return member.id in self.uploaders

    async def gif_actions(self) -> list[dict]:
        self.actions_reads += 1
        return [{"name": "bite", "count": 22}, {"name": "bow", "count": 20}]

    async def gif_page(self, action: str, pool: str, user_id: int, page: int) -> dict:
        if action not in ("bite", "bow") or pool not in POOLS:
            raise LookupError(action)
        self.page_requests.append((action, pool, user_id, page))
        names = self.gifs.get((action, pool), [])
        gifs = [{"name": n, "mine": self.mine.get(n, 0), "ai": n in self.ai} for n in names]
        return {"gifs": gifs, "page": page, "pages": self.pages}

    async def gif_path(self, action: str, name: str) -> Path | None:
        path = self.folder / action / name
        return path if action in ("bite", "bow") and "/" not in name and path.is_file() else None

    async def gif_vote(self, user_id: int, action: str, name: str, value: int) -> None:
        if await self.gif_path(action, name) is None:
            raise LookupError(name)
        self.votes.append((user_id, action, name, value))

    async def gif_vote_totals(self) -> list[dict]:
        return self.totals

    async def submit_gif(self, member: Any, action: str, fp: Any) -> None:
        self.files.append(fp)
        if self.refuse:
            raise ValueError(self.refuse)
        self.submitted.append((member.id, action, fp.read()))


@pytest.fixture
def rp(ms: SimpleNamespace, tmp_path: Path) -> _FakeRoleplay:
    fake = _FakeRoleplay(tmp_path)
    ms.cogs["Roleplay"] = fake
    for action in ("bite", "bow"):
        (tmp_path / action).mkdir()
    (tmp_path / "bite" / "bite_a.gif").write_bytes(GIF)
    (tmp_path / "bite" / "bite_wlw_d.gif").write_bytes(GIF)
    (tmp_path / "secret.txt").write_text("no")
    fake.gifs = {
        ("bite", "default"): ["bite_a.gif", "bite_mlw_b.gif"],
        ("bite", "wlw"): ["bite_wlw_d.gif"],
        ("bite", "mlm"): [],
    }
    return fake


def _staff_headers(ms: SimpleNamespace, user_id: int = STAFF) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    ms.cog.sessions[token] = Session(user_id, CSRF, time.monotonic() + 3600)
    return {"Cookie": f"{SESSION_COOKIE}={token}"}


# --- headers and request limits -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_files_that_ask_for_it_are_cached(ms: SimpleNamespace, tmp_path: Path) -> None:
    uni = _unicornia(ms)
    art = tmp_path / "cotton.webp"
    art.write_bytes(b"webp")
    uni.art[REGULAR] = {"cotton"}
    uni.art_files["cotton"] = art
    headers = _log_in(ms, REGULAR)

    page = await ms.client.get("/", headers=headers)
    script = await ms.client.get("/static/site.js", headers=headers)
    font = await ms.client.get("/static/fonts/nunito-latin-400-normal.woff2", headers=headers)
    served = await ms.client.get("/me/stable/art/cotton.webp", headers=headers)
    card = await ms.client.get("/me/stable/card.webp", headers=headers)

    assert page.headers["Cache-Control"] == "no-store"
    assert script.headers["Cache-Control"] == "no-store"
    assert font.headers["Cache-Control"] == "public, max-age=604800, immutable"
    assert served.headers["Cache-Control"] == "private, max-age=300"
    assert card.headers["Cache-Control"] == "private, max-age=30"


@pytest.mark.asyncio
async def test_member_script_may_call_the_site_and_staff_script_may_not(ms: SimpleNamespace) -> None:
    member = await ms.client.get("/", headers=_log_in(ms, REGULAR))
    staff = await ms.staff.get("/logged-out")

    member_policy = member.headers["Content-Security-Policy"].split("; ")
    assert "connect-src 'self'" in member_policy and "script-src 'self'" in member_policy
    assert member.headers["Content-Security-Policy"] == MEMBER_SECURITY_HEADERS["Content-Security-Policy"]
    assert "connect-src" not in staff.headers["Content-Security-Policy"]
    assert staff.headers["Content-Security-Policy"] == SECURITY_HEADERS["Content-Security-Policy"]


@pytest_asyncio.fixture
async def small(ms: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[TestClient]:
    """A member site whose normal request limit is 1000 bytes and whose gif upload limit is 5000."""
    monkeypatch.setattr(dashboard_module, "MEMBER_MAX_BODY", 1000)
    monkeypatch.setattr(dashboard_module, "GIF_UPLOAD_MAX_BODY", 5000)
    client = TestClient(TestServer(ms.cog.make_member_app()))
    await client.start_server()
    yield client
    await client.close()


async def _send(
    ms: SimpleNamespace, client: TestClient, user_id: int, path: str, size: int, *, csrf: bool = True
) -> aiohttp.ClientResponse:
    form = _upload("file", b"GIF89a" + b"x" * (size - 6), "cute.gif", action="bite")
    if csrf:
        form.add_field("csrf", CSRF)
    return await client.post(path, data=form, headers=_log_in(ms, user_id), allow_redirects=False)


@pytest.mark.asyncio
async def test_someone_who_may_upload_gets_the_large_limit_on_the_upload_route_only(
    ms: SimpleNamespace, rp: _FakeRoleplay, small: TestClient
) -> None:
    accepted = await _send(ms, small, ACTIVE, "/gifs/upload", 3000)
    too_big = await _send(ms, small, ACTIVE, "/gifs/upload", 6000)
    elsewhere = await _send(ms, small, ACTIVE, "/commands", 3000)

    assert accepted.status == 303
    assert [(who, len(data)) for who, _action, data in rp.submitted] == [(ACTIVE, 3000)]
    assert too_big.status == 413
    assert elsewhere.status == 413
    assert len(rp.submitted) == 1
    assert ms.cc.created == []


@pytest.mark.asyncio
async def test_someone_who_may_not_upload_gets_the_normal_limit(
    ms: SimpleNamespace, rp: _FakeRoleplay, small: TestClient
) -> None:
    response = await _send(ms, small, REGULAR, "/gifs/upload", 3000)

    assert response.status == 413
    assert rp.submitted == []


@pytest.mark.asyncio
async def test_the_large_limit_still_needs_the_csrf_token(
    ms: SimpleNamespace, rp: _FakeRoleplay, small: TestClient
) -> None:
    response = await _send(ms, small, ACTIVE, "/gifs/upload", 3000, csrf=False)

    assert response.status == 403
    assert rp.submitted == []


def test_the_gif_upload_limit_is_100_mb_and_the_normal_one_9_mb() -> None:
    assert dashboard_module.GIF_UPLOAD_MAX_BODY == 100 * 1024 * 1024
    assert dashboard_module.MEMBER_MAX_BODY == 9 * 1024 * 1024


# --- member pages ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_list_shows_every_action_with_its_count(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    status, page = await _get(ms, REGULAR, "/gifs")

    assert status == 200
    assert re.search(r'<a href="/gifs/bite">Bite</a>\s*<span class="badge">22</span>', page)
    assert re.search(r'<a href="/gifs/bow">Bow</a>\s*<span class="badge">20</span>', page)
    assert 'href="/gifs"' in page  # the top bar
    assert "/gifs/upload" not in page


@pytest.mark.asyncio
async def test_each_pool_has_its_own_page_with_tabs_and_the_gifs_the_cog_returned(
    ms: SimpleNamespace, rp: _FakeRoleplay
) -> None:
    default = (await _get(ms, REGULAR, "/gifs/bite"))[1]
    wlw = (await _get(ms, REGULAR, "/gifs/bite/wlw"))[1]
    mlm_status, mlm = await _get(ms, REGULAR, "/gifs/bite/mlm")

    assert "bite_a.gif" in default and "bite_mlw_b.gif" in default and "bite_wlw_d.gif" not in default
    assert "bite_wlw_d.gif" in wlw and "bite_a.gif" not in wlw
    assert mlm_status == 200 and "No gifs here yet." in mlm
    for page in (default, wlw, mlm):
        assert 'href="/gifs/bite"' in page and 'href="/gifs/bite/wlw"' in page and 'href="/gifs/bite/mlm"' in page
    assert 'src="/gifs/bite/file/bite_a.gif" alt="Bite gif 1" loading="lazy"' in default
    assert rp.page_requests[:3] == [
        ("bite", "default", REGULAR, 1),
        ("bite", "wlw", REGULAR, 1),
        ("bite", "mlm", REGULAR, 1),
    ]


def _visible_text(page: str) -> str:
    """The page as a reader sees it: no tags, so no attributes such as the image address or alt text."""
    return re.sub(r"<[^>]+>", " ", page)


@pytest.mark.asyncio
async def test_members_are_not_shown_file_names(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    rp.ai = {"bite_mlw_b.gif"}

    _, page = await _get(ms, REGULAR, "/gifs/bite")

    assert "bite_a.gif" not in _visible_text(page) and "bite_mlw_b.gif" not in _visible_text(page)
    assert 'alt="bite_a.gif"' not in page and 'alt="bite_mlw_b.gif' not in page
    assert 'alt="Bite gif 1"' in page and 'alt="Bite gif 2, made with AI"' in page
    assert 'src="/gifs/bite/file/bite_a.gif"' in page  # the image itself, and the vote form, still name the file


@pytest.mark.asyncio
async def test_only_ai_made_gifs_get_the_badge(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    rp.ai = {"bite_mlw_b.gif"}

    _, page = await _get(ms, REGULAR, "/gifs/bite")
    _, plain = await _get(ms, REGULAR, "/gifs/bite/wlw")

    first, second = page.split('<article class="gif"')[1:]
    assert "badge ai" not in first
    assert '<span class="badge ai" title="Made with AI">AI</span>' in second
    assert "badge ai" not in plain


@pytest.mark.asyncio
async def test_staff_still_see_the_file_names(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    rp.totals = [{"action": "bite", "name": "bite_eros_9.gif", "up": 1, "down": 0}]

    response = await ms.staff.get("/gifs", headers=_staff_headers(ms))

    assert "bite_eros_9.gif" in _visible_text(await response.text())


@pytest.mark.asyncio
async def test_page_links_go_to_the_previous_and_next_page_of_the_same_pool(
    ms: SimpleNamespace, rp: _FakeRoleplay
) -> None:
    _, middle = await _get(ms, REGULAR, "/gifs/bite/wlw?page=2")
    _, first = await _get(ms, REGULAR, "/gifs/bite?page=1")

    assert 'href="/gifs/bite/wlw?page=1"' in middle and 'href="/gifs/bite/wlw?page=3"' in middle
    assert "Page 2 of 3" in middle
    assert "Previous" not in first and 'href="/gifs/bite?page=2"' in first


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "asked"),
    [
        ("page=abc", 1),
        ("page=-3", 1),
        ("page=0", 1),
        ("", 1),
        ("page=7", 7),
        ("page=99999999999", MAX_PAGE),  # past the end: the cog shows the last page
        ("page=" + "9" * 5000, MAX_PAGE),  # more digits than Python will convert
    ],
)
async def test_a_bad_page_number_is_the_first_page_and_a_huge_one_the_last(
    ms: SimpleNamespace, rp: _FakeRoleplay, query: str, asked: int
) -> None:
    status, _ = await _get(ms, REGULAR, f"/gifs/bite?{query}")

    assert status == 200
    assert rp.page_requests[0][3] == asked


@pytest.mark.asyncio
async def test_only_members_who_can_send_in_a_gif_cause_the_folders_to_be_read_for_the_form(
    ms: SimpleNamespace, rp: _FakeRoleplay
) -> None:
    await _get(ms, REGULAR, "/gifs/bite")
    assert rp.actions_reads == 0

    await _get(ms, ACTIVE, "/gifs/bite")
    assert rp.actions_reads == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/gifs/notanaction", "/gifs/notanaction/wlw", "/gifs/bite/mlw", "/gifs/bite/file/nope.gif"]
)
async def test_unknown_things_are_404(ms: SimpleNamespace, rp: _FakeRoleplay, path: str) -> None:
    status, _ = await _get(ms, REGULAR, path)

    assert status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/gifs", "/gifs/bite", "/gifs/bite/wlw", "/gifs/bite/file/bite_a.gif"])
async def test_every_gif_page_needs_the_roleplay_cog(ms: SimpleNamespace, rp: _FakeRoleplay, path: str) -> None:
    del ms.cogs["Roleplay"]

    status, page = await _get(ms, REGULAR, path)

    assert status == 503 and "not available right now" in page


@pytest.mark.asyncio
async def test_the_gif_file_is_served_privately_and_only_from_the_folder(
    ms: SimpleNamespace, rp: _FakeRoleplay
) -> None:
    headers = _log_in(ms, REGULAR)

    served = await ms.client.get("/gifs/bite/file/bite_a.gif", headers=headers)
    missing = await ms.client.get("/gifs/bite/file/bite_zzz.gif", headers=headers)
    outside = await ms.client.get("/gifs/bite/file/..%2Fsecret.txt", headers=headers)
    other_action = await ms.client.get("/gifs/notanaction/file/bite_a.gif", headers=headers)
    anonymous = await ms.client.get("/gifs/bite/file/bite_a.gif", allow_redirects=False)

    assert served.status == 200 and await served.read() == GIF
    assert served.headers["Content-Type"] == "image/gif"
    assert served.headers["Cache-Control"] == "private, max-age=86400"
    assert served.headers["X-Content-Type-Options"] == "nosniff"
    assert (missing.status, outside.status, other_action.status) == (404, 404, 404)
    assert (anonymous.status, anonymous.headers["Location"]) == (302, "/logged-out")


@pytest.mark.asyncio
async def test_user_text_on_the_pages_is_escaped(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    rp.gifs[("bite", "default")] = ["<script>alert(1)</script>.gif"]

    _, page = await _get(ms, REGULAR, "/gifs/bite")

    assert "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page


# --- voting ---------------------------------------------------------------------------------------

VOTE = {"action": "bite", "name": "bite_a.gif", "value": "up", "pool": "wlw", "page": "2", "slot": "3"}


@pytest.mark.asyncio
async def test_the_vote_form_shows_the_members_own_vote_and_takes_it_back_when_pressed_again(
    ms: SimpleNamespace, rp: _FakeRoleplay
) -> None:
    rp.mine = {"bite_a.gif": 1, "bite_mlw_b.gif": -1}
    rp.totals = [{"action": "bite", "name": "bite_a.gif", "up": 99, "down": 88}]

    _, page = await _get(ms, REGULAR, "/gifs/bite")

    first, second = page.split('<article class="gif"')[1:]
    assert 'value="none" aria-pressed="true" aria-label="Thumbs up"' in first
    assert 'value="down" aria-pressed="false" aria-label="Thumbs down"' in first
    assert 'value="up" aria-pressed="false" aria-label="Thumbs up"' in second
    assert 'value="none" aria-pressed="true" aria-label="Thumbs down"' in second
    assert "99" not in page and "88" not in page  # no totals for members
    assert 'id="g1"' in first and 'id="g2"' in second


@pytest.mark.asyncio
async def test_a_plain_vote_saves_and_returns_to_the_same_gif(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    response = await _post(ms, REGULAR, "/gifs/vote", VOTE)

    assert response.status == 303 and response.headers["Location"] == "/gifs/bite/wlw?page=2#g3"
    assert rp.votes == [(REGULAR, "bite", "bite_a.gif", 1)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("sent", "value"), [("up", 1), ("down", -1), ("none", 0)])
async def test_up_down_and_none_are_one_zero_and_minus_one(
    ms: SimpleNamespace, rp: _FakeRoleplay, sent: str, value: int
) -> None:
    await _post(ms, ACTIVE, "/gifs/vote", {**VOTE, "value": sent, "pool": "default"})

    assert rp.votes == [(ACTIVE, "bite", "bite_a.gif", value)]


@pytest.mark.asyncio
async def test_the_default_pool_goes_back_to_the_action_page(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    response = await _post(ms, REGULAR, "/gifs/vote", {**VOTE, "pool": "default", "page": "1", "slot": "5"})

    assert response.headers["Location"] == "/gifs/bite?page=1#g5"


@pytest.mark.asyncio
async def test_a_vote_from_the_script_gets_no_redirect(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    headers = {**_log_in(ms, REGULAR), "X-Requested-With": "fetch"}

    response = await ms.client.post("/gifs/vote", data={"csrf": CSRF, **VOTE}, headers=headers, allow_redirects=False)

    assert response.status == 204
    assert rp.votes == [(REGULAR, "bite", "bite_a.gif", 1)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        {"value": "maybe"},
        {"value": ""},
        {"pool": "https://evil.example"},
        {"pool": "mlw"},
        {"pool": "//evil.example"},
        {"page": "abc"},
        {"page": "0"},
        {"page": "99999999"},
        {"page": "-1"},
        {"slot": "0"},
        {"slot": "abc"},
        {"slot": "51"},
        {"page": "9" * 5000},
        {"slot": "9" * 5000},
    ],
)
async def test_a_bad_vote_form_is_refused_and_nothing_is_stored(
    ms: SimpleNamespace, rp: _FakeRoleplay, bad: dict[str, str]
) -> None:
    response = await _post(ms, REGULAR, "/gifs/vote", {**VOTE, **bad})

    assert response.status == 400
    assert rp.votes == []


@pytest.mark.asyncio
async def test_a_vote_for_a_gif_that_does_not_exist_is_404(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    for bad in ({"name": "bite_zzz.gif"}, {"action": "notanaction"}, {"name": "../secret.txt"}):
        response = await _post(ms, REGULAR, "/gifs/vote", {**VOTE, **bad})
        assert response.status == 404, bad

    assert rp.votes == []


@pytest.mark.asyncio
async def test_a_vote_needs_the_cog_and_the_csrf_token(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    forged = await ms.client.post("/gifs/vote", data=VOTE, headers=_log_in(ms, REGULAR), allow_redirects=False)
    del ms.cogs["Roleplay"]
    unavailable = await _post(ms, REGULAR, "/gifs/vote", VOTE)

    assert forged.status == 403 and unavailable.status == 503
    assert rp.votes == []


# --- sending in a gif -------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [ACTIVE, INACTIVE])
async def test_members_who_may_upload_see_the_form_and_the_action_is_preselected(
    ms: SimpleNamespace, rp: _FakeRoleplay, user_id: int
) -> None:
    _, index = await _get(ms, user_id, "/gifs")
    _, action_page = await _get(ms, user_id, "/gifs/bite/wlw?page=2")

    assert 'action="/gifs/upload"' in index and 'enctype="multipart/form-data"' in index
    assert '<option value="bite" selected>' not in index
    assert '<option value="bite" selected>' in action_page and '<option value="bow">' in action_page
    assert '<input type="hidden" name="from" value="bite">' in action_page
    assert '<input type="hidden" name="pool" value="wlw">' in action_page
    assert '<input type="hidden" name="page" value="2">' in action_page


@pytest.mark.asyncio
async def test_other_members_see_no_form_and_cannot_post_one(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    _, index = await _get(ms, REGULAR, "/gifs")
    _, action_page = await _get(ms, REGULAR, "/gifs/bite")
    response = await _post(ms, REGULAR, "/gifs/upload", _upload("file", GIF, "cute.gif", action="bite"))

    assert "/gifs/upload" not in index and "/gifs/upload" not in action_page
    assert response.status == 403
    assert rp.submitted == []


@pytest.mark.asyncio
async def test_an_upload_is_handed_to_the_cog_with_the_action_and_the_bytes(
    ms: SimpleNamespace, rp: _FakeRoleplay
) -> None:
    response = await _post(ms, ACTIVE, "/gifs/upload", _upload("file", GIF, "../../x.gif", action="bite"))

    assert response.status == 303 and response.headers["Location"] == "/gifs?sent=1"
    assert rp.submitted == [(ACTIVE, "bite", GIF)]
    assert rp.files[0].closed  # the upload's temporary file doesn't wait for the garbage collector
    _, page = await _get(ms, ACTIVE, "/gifs?sent=1")
    assert "sent to the staff" in page
    _, plain = await _get(ms, ACTIVE, "/gifs")
    assert "sent to the staff" not in plain


@pytest.mark.asyncio
async def test_an_upload_from_an_action_page_returns_to_that_page(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    form = _upload("file", GIF, "cute.gif", action="bow", **{"from": "bite"}, pool="wlw", page="2")

    response = await _post(ms, ACTIVE, "/gifs/upload", form)

    assert response.status == 303 and response.headers["Location"] == "/gifs/bite/wlw?page=2&sent=1"
    assert rp.submitted == [(ACTIVE, "bow", GIF)]
    _, page = await _get(ms, ACTIVE, "/gifs/bite/wlw?page=2&sent=1")
    assert "sent to the staff" in page


@pytest.mark.asyncio
async def test_a_refused_upload_shows_the_message_escaped_with_400(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    rp.refuse = "Only <b>GIF</b> files are accepted."

    index = await _post(ms, ACTIVE, "/gifs/upload", _upload("file", GIF, "cute.gif", action="bite"))
    on_page = await _post(
        ms,
        ACTIVE,
        "/gifs/upload",
        _upload("file", GIF, "cute.gif", action="bite", **{"from": "bite"}, pool="wlw", page="2"),
    )

    for response in (index, on_page):
        page = await response.text()
        assert response.status == 400
        assert "Only &lt;b&gt;GIF&lt;/b&gt; files are accepted." in page and "<b>GIF</b>" not in page
    assert rp.submitted == []


@pytest.mark.asyncio
async def test_no_file_chosen_is_a_400_with_a_message(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    response = await _post(ms, ACTIVE, "/gifs/upload", _upload("file", b"", "", action="bite"))

    assert response.status == 400 and "Choose a GIF" in await response.text()
    assert rp.submitted == []


@pytest.mark.asyncio
async def test_a_bad_return_page_falls_back_to_the_list(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    for extra in ({"pool": "https://evil.example", "page": "2"}, {"pool": "wlw", "page": "x"}, {}):
        form = _upload("file", GIF, "cute.gif", action="bite", **{"from": "https://evil.example"}, **extra)
        response = await _post(ms, ACTIVE, "/gifs/upload", form)
        assert response.status == 303 and response.headers["Location"] == "/gifs?sent=1", extra


# --- the staff site -------------------------------------------------------------------------------


def _rows(count: int) -> list[dict]:
    return [{"action": "bite", "name": f"bite_{n:02}.gif", "up": n, "down": 1} for n in range(count)]


@pytest.mark.asyncio
async def test_staff_see_voted_gifs_with_totals_in_the_order_the_cog_gave(
    ms: SimpleNamespace, rp: _FakeRoleplay
) -> None:
    rp.totals = [
        {"action": "bite", "name": "bite_a.gif", "up": 3, "down": 1},
        {"action": "bow", "name": "bow_1.gif", "up": 0, "down": 7},
    ]

    response = await ms.staff.get("/gifs", headers=_staff_headers(ms))
    page = await response.text()

    assert response.status == 200
    assert page.index("bite_a.gif") < page.index("bow_1.gif")
    assert re.search(r'<td class="num up">3</td>\s*<td class="num down">1</td>', page)
    assert re.search(r'<td class="num up">0</td>\s*<td class="num down">7</td>', page)
    assert 'src="/gifs/bite/file/bite_a.gif"' in page and 'src="/gifs/bow/file/bow_1.gif"' in page
    assert 'href="/gifs"' in page and "Gif votes" in page  # the top bar


@pytest.mark.asyncio
async def test_staff_pages_hold_ten(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    rp.totals = _rows(25)
    headers = _staff_headers(ms)

    first = await (await ms.staff.get("/gifs", headers=headers)).text()
    last = await (await ms.staff.get("/gifs?page=3", headers=headers)).text()
    past = await (await ms.staff.get("/gifs?page=99", headers=headers)).text()
    junk = await (await ms.staff.get("/gifs?page=abc", headers=headers)).text()

    huge = await (await ms.staff.get("/gifs?page=" + "9" * 5000, headers=headers)).text()

    assert "Page 3 of 3" in huge
    assert first.count("<tr>") == 1 + 10 and "Page 1 of 3" in first and "Previous" not in first
    assert last.count("<tr>") == 1 + 5 and "Page 3 of 3" in last and "Next" not in last
    assert "bite_24.gif" in last and "bite_24.gif" not in first
    assert "Page 3 of 3" in past
    assert "Page 1 of 3" in junk


@pytest.mark.asyncio
async def test_no_votes_says_so(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    response = await ms.staff.get("/gifs", headers=_staff_headers(ms))

    assert response.status == 200 and "No votes yet." in await response.text()


@pytest.mark.asyncio
async def test_staff_pages_need_the_roleplay_cog(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    del ms.cogs["Roleplay"]
    headers = _staff_headers(ms)

    votes = await ms.staff.get("/gifs", headers=headers)
    file = await ms.staff.get("/gifs/bite/file/bite_a.gif", headers=headers)

    assert votes.status == 503 and file.status == 503


@pytest.mark.asyncio
async def test_staff_get_the_gif_file_uncached_and_only_from_the_folder(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    headers = _staff_headers(ms)

    served = await ms.staff.get("/gifs/bite/file/bite_a.gif", headers=headers)
    outside = await ms.staff.get("/gifs/bite/file/..%2Fsecret.txt", headers=headers)

    assert served.status == 200 and await served.read() == GIF
    assert served.headers["Cache-Control"] == "no-store"
    assert outside.status == 404


@pytest.mark.asyncio
async def test_the_staff_gif_routes_need_a_staff_session_and_only_read(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    anonymous = await ms.staff.get("/gifs", allow_redirects=False)
    file = await ms.staff.get("/gifs/bite/file/bite_a.gif", allow_redirects=False)
    as_member = await ms.staff.get("/gifs", headers=_log_in(ms, REGULAR), allow_redirects=False)
    not_staff = await ms.staff.get("/gifs", headers=_staff_headers(ms, REGULAR), allow_redirects=False)

    for response in (anonymous, file, as_member, not_staff):
        assert (response.status, response.headers["Location"]) == (302, "/logged-out")
    gif_routes = [r for r in ms.staff.app.router.routes() if r.resource and r.resource.canonical.startswith("/gifs")]
    assert gif_routes and {r.method for r in gif_routes} <= {"GET", "HEAD"}  # aiohttp adds HEAD to a GET


@pytest.mark.asyncio
async def test_members_never_get_the_totals(ms: SimpleNamespace, rp: _FakeRoleplay) -> None:
    rp.totals = [{"action": "bite", "name": "bite_a.gif", "up": 42, "down": 17}]

    for path in ("/gifs", "/gifs/bite", "/gifs/bite/wlw"):
        status, page = await _get(ms, ACTIVE, path)
        assert status == 200 and "42" not in page and "17" not in page and "Gif votes" not in page, path
