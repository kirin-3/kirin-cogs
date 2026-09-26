"""The staff site's modmail pages, read from a temporary database with modmail's schema. Discord is mocked."""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

import dashboard.modmail as modmail
from dashboard.modmail import AttachmentLinks, Unavailable, classify
from dashboard.tests.test_dashboard import _ban, _FakeBanLog, _log_in, site  # noqa: F401

REPEAT_USER = "400000000000000001"  # opened threads 10, 20 and 30
SIGNED = "https://cdn.discordapp.com/attachments/1/2/shot.PNG?ex=66000000&is=65000000&hm=abc&"
OLD = "https://cdn.discordapp.com/attachments/1/4/old.png"
VIDEO = "https://cdn.discordapp.com/attachments/1/3/clip.mp4"
NOT_SAVED = "Attachment could not be saved: file too large"

# The columns modmail's migrations leave on threads and thread_messages; like the live database, no index on
# thread_messages.thread_id or threads.user_id.
SCHEMA = """
CREATE TABLE threads (
    id varchar(36) PRIMARY KEY NOT NULL, status integer NOT NULL, is_legacy integer NOT NULL,
    user_id varchar(20) NOT NULL, user_name varchar(128) NOT NULL, channel_id varchar(20) UNIQUE,
    created_at datetime NOT NULL, thread_number integer UNIQUE, metadata text, log_storage_type varchar(255),
    log_storage_data text, next_message_number integer DEFAULT 1, alert_ids text
);
CREATE TABLE thread_messages (
    id integer PRIMARY KEY AUTOINCREMENT NOT NULL, thread_id varchar(36) NOT NULL, message_type integer NOT NULL,
    user_id varchar(20), user_name varchar(128) NOT NULL, body text NOT NULL, is_anonymous integer NOT NULL,
    dm_message_id varchar(20) UNIQUE, created_at datetime NOT NULL, message_number integer,
    inbox_message_id varchar(20) UNIQUE, dm_channel_id varchar(20), role_name varchar(255), attachments text,
    small_attachments text, use_legacy_format boolean, metadata text
);
"""


def _message(thread: str, kind: int, body: str = "", when: str = "2024-01-01 10:00:00", **extra: Any) -> dict:
    return {
        "thread_id": thread,
        "message_type": kind,
        "user_id": "1",
        "user_name": extra.pop("user_name", "member1"),
        "body": body,
        "is_anonymous": 0,
        "created_at": when,
        **extra,
    }


def _build(path: Path) -> Path:
    """55 threads, one a day from 2024-01-01; thread 1 holds every kind of message."""
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    for n in range(1, 56):
        user_id = REPEAT_USER if n in (10, 20, 30) else str(500000000000000000 + n)
        name = {42: "sparkle_pony", 2: "<script>alert(1)</script>"}.get(n, f"member{n}")
        db.execute(
            "INSERT INTO threads (id, status, is_legacy, user_id, user_name, created_at, thread_number) "
            "VALUES (?, ?, 0, ?, ?, ?, ?)",
            (
                f"t{n}",
                1 if n == 55 else 2,
                user_id,
                name,
                f"2024-{1 + (n - 1) // 28:02d}-{1 + (n - 1) % 28:02d} 09:00:00",
                n,
            ),
        )
    messages = [
        _message("t1", 1, "Thread was opened by member1", "2024-01-01 09:00:00", user_name="Modmail"),
        _message("t1", 3, "Hi, I need help\nsecond line", attachments=json.dumps([SIGNED, VIDEO, NOT_SAVED])),
        _message("t1", 3, "", attachments=json.dumps([OLD])),
        _message(
            "t1",
            4,
            "We'll look into it",
            "2024-01-01 10:05:00",
            user_name="RealMod",
            is_anonymous=1,
            role_name="Moderator",
        ),
        _message("t1", 4, "Named reply", "2024-01-01 10:06:00", user_name="OtherMod", role_name="Admin"),
        _message("t1", 2, "internal note", "2024-01-01 10:07:00", user_name="RealMod"),
        _message("t1", 6, "!close", "2024-01-01 10:08:00", user_name="RealMod"),
        _message("t1", 7, "Thanks for contacting us", "2024-01-01 10:09:00", user_name="Modmail"),
        _message(
            "t1",
            8,
            "",
            "2024-01-01 10:10:00",
            user_name="RealMod",
            metadata=json.dumps({"originalThreadMessage": {"body": "old text"}, "newBody": "new text"}),
        ),
        _message(
            "t1",
            9,
            "",
            "2024-01-01 10:11:00",
            user_name="RealMod",
            metadata=json.dumps({"originalThreadMessage": {"body": "oops"}}),
        ),
        _message(
            "t1",
            3,
            "look",
            "2024-01-01 10:12:00",
            metadata=json.dumps(
                {"embeds": [{"title": "Embed title", "description": "Embed text"}], "forwardedEmbeds": None}
            ),
        ),
        _message("t1", 3, "broken", "2024-01-01 10:13:00", metadata="not json", attachments="also not json"),
        _message("t2", 3, "<script>x</script>", user_name="<script>alert(1)</script>"),
        _message("t3", 3, "is 50% off a_b real?"),
        _message("t7", 3, "I want a Refund"),
        _message("t8", 3, "refund please"),
        _message("t8", 3, "refund again"),  # two matches in one thread still list it once
    ]
    for row in messages:
        db.execute(
            f"INSERT INTO thread_messages ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
        )
    db.commit()
    db.close()
    return path


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = _build(tmp_path / "data.sqlite")
    monkeypatch.setattr(modmail, "DB_PATH", path)
    return path


# --- query classification ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", ("all", "")),
        ("   ", ("all", "")),
        ("#0", ("number", 0)),
        ("4829", ("number", 4829)),
        ("#4829", ("number", 4829)),
        ("1" * 16, ("number", int("1" * 16))),
        ("1" * 17, ("user", "1" * 17)),
        ("1" * 20, ("user", "1" * 20)),
        ("1" * 21, ("text", "1" * 21)),
        ("#" + "1" * 17, ("text", "#" + "1" * 17)),
        ("50%", ("text", "50%")),
        ("a_b", ("text", "a_b")),
        (" refund ", ("text", "refund")),
    ],
)
def test_classify(query: str, expected: tuple) -> None:
    assert classify(query) == expected


# --- the store -----------------------------------------------------------------------------------


def _numbers(threads: list[dict[str, Any]]) -> list[int]:
    return [thread["number"] for thread in threads]


@pytest.mark.asyncio
async def test_list_is_newest_first_in_pages_of_50(db: Path) -> None:
    first, more = await modmail.list_threads("", 0)
    last, no_more = await modmail.list_threads("", 1)

    assert _numbers(first) == list(range(55, 5, -1)) and more
    assert _numbers(last) == [5, 4, 3, 2, 1] and not no_more
    assert first[0] == {
        "number": 55,
        "status": "Open",
        "user_id": "500000000000000055",
        "user_name": "member55",
        "opened": first[0]["opened"],
    }
    assert first[1]["status"] == "Closed"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (REPEAT_USER, [30, 20, 10]),
        ("#42", [42]),
        ("42", [42]),
        ("#0", []),
        ("refund", [8, 7]),
        ("PONY", [42]),
        ("50%", [3]),
        ("%", [3]),  # a literal percent sign, not a wildcard
        ("a_b", [3]),
        ("x_y", []),
        ("nothing like this", []),
    ],
)
@pytest.mark.asyncio
async def test_search(db: Path, query: str, expected: list[int]) -> None:
    threads, more = await modmail.list_threads(query, 0)

    assert _numbers(threads) == expected and not more


@pytest.mark.asyncio
async def test_thread_messages_are_oldest_first_with_their_details(db: Path) -> None:
    found = await modmail.get_thread(1)
    assert found is not None
    thread, messages = found

    assert thread["number"] == 1 and thread["user_name"] == "member1"
    kinds = [m["kind"] for m in messages]
    assert kinds == [
        "system", "member", "member", "reply", "reply", "chat", "command", "to-member", "edited", "deleted", "member",
        "member",
    ]  # fmt: skip
    # The two member messages at 10:00 keep their insert order.
    assert messages[1]["body"] == "Hi, I need help\nsecond line" and messages[2]["body"] == ""
    assert messages[1]["attachments"] == [SIGNED, VIDEO, NOT_SAVED]
    assert messages[3]["name"] == "RealMod" and messages[3]["role"] == "Moderator"
    assert messages[4]["role"] is None  # not anonymous, so the role isn't shown as a disguise
    assert (messages[8]["before"], messages[8]["after"]) == ("old text", "new text")
    assert messages[9]["before"] == "oops"
    assert messages[10]["embeds"] == [{"title": "Embed title", "description": "Embed text", "url": ""}]
    assert messages[11]["embeds"] == [] and messages[11]["attachments"] == []
    assert messages[0]["when"] == 1704099600.0


@pytest.mark.asyncio
async def test_unknown_thread_is_none(db: Path) -> None:
    assert await modmail.get_thread(999) is None


@pytest.mark.asyncio
async def test_threads_for_user(db: Path) -> None:
    assert _numbers(await modmail.threads_for_user(int(REPEAT_USER))) == [30, 20, 10]
    assert await modmail.threads_for_user(1) == []


@pytest.mark.asyncio
async def test_reads_leave_the_file_unchanged(db: Path) -> None:
    before = db.read_bytes()

    await modmail.list_threads("", 0)
    await modmail.list_threads("refund", 0)
    await modmail.get_thread(1)
    await modmail.threads_for_user(int(REPEAT_USER))

    assert db.read_bytes() == before
    assert sorted(p.name for p in db.parent.iterdir()) == ["data.sqlite"]


@pytest.mark.parametrize("state", ["missing", "corrupt"])
@pytest.mark.asyncio
async def test_unreadable_database_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    path = tmp_path / "data.sqlite"
    if state == "corrupt":
        path.write_bytes(b"this is not a database" * 100)
    monkeypatch.setattr(modmail, "DB_PATH", path)

    for call in (modmail.list_threads("", 0), modmail.get_thread(1), modmail.threads_for_user(1)):
        with pytest.raises(Unavailable):
            await call
    assert path.exists() == (state == "corrupt")  # never created


# --- attachment links ----------------------------------------------------------------------------


def _signed(url: str) -> str:
    return url.split("?")[0] + "?ex=7fffffff&is=1&hm=fresh"


def _refresher(response: Any = None) -> tuple[AttachmentLinks, AsyncMock]:
    async def refresh(route: Any, *, json: dict) -> dict:
        return {"refreshed_urls": [{"original": url, "refreshed": _signed(url)} for url in json["attachment_urls"]]}

    request = AsyncMock(side_effect=response or refresh)
    return AttachmentLinks(SimpleNamespace(http=SimpleNamespace(request=request))), request


@pytest.mark.asyncio
async def test_links_are_refreshed_in_batches_of_50_and_cached() -> None:
    links, request = _refresher()
    urls = [f"https://cdn.discordapp.com/attachments/1/{n}/f.png" for n in range(120)]

    fresh = await links.refresh([*urls, NOT_SAVED, "https://example.com/x.png"])

    assert [len(call.kwargs["json"]["attachment_urls"]) for call in request.await_args_list] == [50, 50, 20]
    assert request.await_args_list[0].args[0].path == "/attachments/refresh-urls"
    assert fresh == {url: _signed(url) for url in urls}

    again = await links.refresh(urls[:3])
    assert request.await_count == 3 and again == {url: _signed(url) for url in urls[:3]}


@pytest.mark.asyncio
async def test_links_without_an_expiry_are_not_cached() -> None:
    async def unsigned(route: Any, *, json: dict) -> dict:
        return {"refreshed_urls": [{"original": u, "refreshed": u.split("?")[0]} for u in json["attachment_urls"]]}

    links, request = _refresher(unsigned)

    await links.refresh([OLD])
    await links.refresh([OLD])

    assert request.await_count == 2


@pytest.mark.asyncio
async def test_refused_or_omitted_links_are_missing() -> None:
    async def partial(route: Any, *, json: dict) -> dict:
        return {"refreshed_urls": [{"original": SIGNED, "refreshed": _signed(SIGNED)}]}

    links, _ = _refresher(partial)
    assert await links.refresh([SIGNED, OLD]) == {SIGNED: _signed(SIGNED)}

    links, _ = _refresher(discord.HTTPException(MagicMock(status=400, reason="Bad Request"), "no"))
    assert await links.refresh([SIGNED, OLD]) == {}


# --- pages ---------------------------------------------------------------------------------------


@pytest.fixture
def refresh(site: SimpleNamespace) -> AsyncMock:  # noqa: F811
    async def signed(route: Any, *, json: dict) -> dict:
        return {
            "refreshed_urls": [
                {"original": u, "refreshed": _signed(u)} for u in json["attachment_urls"] if "old.png" not in u
            ]
        }

    site.bot.http.request = AsyncMock(side_effect=signed)
    return site.bot.http.request


@pytest.mark.asyncio
async def test_list_page(site: SimpleNamespace, db: Path) -> None:  # noqa: F811
    body = await (await site.client.get("/modmail", headers=_log_in(site))).text()

    assert 'href="/modmail/55"' in body and "member55" in body and "500000000000000055" in body
    assert 'href="/modmail/5"' not in body
    assert 'href="/modmail?page=1&amp;q="' in body and "Newer" not in body
    assert 'class="on">Modmail<' in body

    last = await (await site.client.get("/modmail", params={"page": "1"}, headers=_log_in(site))).text()
    assert 'href="/modmail/1"' in last and "Older" not in last


@pytest.mark.asyncio
async def test_search_page(site: SimpleNamespace, db: Path) -> None:  # noqa: F811
    headers = _log_in(site)

    found = await (await site.client.get("/modmail", params={"q": "refund"}, headers=headers)).text()
    empty = await (await site.client.get("/modmail", params={"q": "zzz"}, headers=headers)).text()

    assert 'href="/modmail/8"' in found and 'href="/modmail/7"' in found and 'href="/modmail/9"' not in found
    assert "No threads match “zzz”." in empty


@pytest.mark.asyncio
async def test_thread_page(site: SimpleNamespace, db: Path, refresh: AsyncMock) -> None:  # noqa: F811
    response = await site.client.get("/modmail/1", headers=_log_in(site))
    body = await response.text()

    assert response.status == 200
    assert "Hi, I need help\nsecond line" in body
    assert "Reply as Moderator (anonymous)" in body and "RealMod" in body
    assert "Staff only, not sent to the member" in body and "!close" in body and "Bot to member" in body
    assert "old text" in body and "new text" in body and "Deleted a reply" in body and "oops" in body
    assert "Embed title" in body and "Embed text" in body
    fresh = _signed(SIGNED).replace("&", "&amp;")
    assert (
        f'<a href="{fresh}" target="_blank" rel="noopener noreferrer"><img src="{fresh}" alt="shot.PNG" loading="lazy">'
        in body
    )
    assert f'<a href="{_signed(VIDEO).replace("&", "&amp;")}"' in body and ">clip.mp4</a>" in body
    assert "<video" not in body
    assert 'old.png <span class="tag">Unavailable</span>' in body
    assert NOT_SAVED in body
    assert refresh.await_count == 1


@pytest.mark.asyncio
async def test_thread_page_survives_a_refresh_error(site: SimpleNamespace, db: Path) -> None:  # noqa: F811
    site.bot.http.request = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500, reason="x"), "down"))

    body = await (await site.client.get("/modmail/1", headers=_log_in(site))).text()

    assert "Hi, I need help" in body and body.count("Unavailable</span>") == 3


@pytest.mark.asyncio
async def test_unknown_thread_is_404(site: SimpleNamespace, db: Path) -> None:  # noqa: F811
    response = await site.client.get("/modmail/999", headers=_log_in(site))

    assert response.status == 404 and "Thread not found" in await response.text()


@pytest.mark.asyncio
async def test_user_text_is_escaped(site: SimpleNamespace, db: Path, refresh: AsyncMock) -> None:  # noqa: F811
    headers = _log_in(site)
    listing = await (await site.client.get("/modmail", params={"page": "1"}, headers=headers)).text()
    thread = await (await site.client.get("/modmail/2", headers=headers)).text()

    for body in (listing, thread):
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
        assert "<script>" not in body
    assert "&lt;script&gt;x&lt;/script&gt;" in thread


@pytest.mark.asyncio
async def test_missing_database_shows_a_notice(
    site: SimpleNamespace,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(modmail, "DB_PATH", tmp_path / "missing.sqlite")
    headers = _log_in(site)

    for path in ("/modmail", "/modmail/1"):
        response = await site.client.get(path, headers=headers)
        assert response.status == 200 and "Modmail logs are unavailable" in await response.text()
    site.bot.get_cog.return_value = _FakeBanLog()
    assert (await site.client.get("/", headers=headers)).status == 200


@pytest.mark.parametrize(
    ("user_id", "expected"),
    [(int(REPEAT_USER), "#30"), (1, "has not opened any modmail threads"), (None, "unavailable right now")],
)
@pytest.mark.asyncio
async def test_ban_page_lists_modmail_threads(
    site: SimpleNamespace,  # noqa: F811
    db: Path,
    monkeypatch: pytest.MonkeyPatch,
    user_id: int | None,
    expected: str,
) -> None:
    if user_id is None:
        monkeypatch.setattr(modmail, "DB_PATH", db.parent / "missing.sqlite")
    banlog = _FakeBanLog()
    banlog.records[7] = {**_ban(7, user_id=user_id or 1), "messages": []}
    site.bot.get_cog.return_value = banlog

    body = await (await site.client.get("/bans/7", headers=_log_in(site))).text()

    assert expected in body
    if user_id == int(REPEAT_USER):
        assert 'href="/modmail/30"' in body and 'href="/modmail/20"' in body and 'href="/modmail/10"' in body
