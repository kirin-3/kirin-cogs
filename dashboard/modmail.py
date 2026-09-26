"""The staff site's modmail pages: every thread the modmail bot has kept, read straight from its SQLite database.

Read-only by construction: the database is opened with mode=ro and every route is a GET. Modmail (a separate Node
bot on the same server) writes the file with a rollback journal and waits up to 1 s when it is busy, so every read
here is one short query. Attachment links expire, so they are re-signed through Discord when a thread is viewed;
the files themselves are never downloaded or stored.
"""

import asyncio
import contextlib
import json
import logging
import re
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import aiohttp
import discord
from aiohttp import web
from discord.http import Route

if TYPE_CHECKING:
    from .dashboard import Dashboard

DB_PATH = Path("/home/kirin/modmail/db/data.sqlite")
PAGE_SIZE = 50
USER_THREADS = 50
MAX_QUERY = 100
REFRESH_BATCH = 50  # Discord's limit per refresh-urls call
REFRESH_MARGIN = 300  # seconds before a signed link expires that it is refreshed again
CDN = "https://cdn.discordapp.com/"
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
STATUS = {1: "Open", 2: "Closed", 3: "Suspended"}
# modmail's message_type values (src/data/constants.js). 5 (legacy) is unused and falls back to "system".
KINDS = {1: "system", 2: "chat", 3: "member", 4: "reply", 6: "command", 7: "to-member", 8: "edited", 9: "deleted"}
THREAD_COLUMNS = "id, thread_number, status, user_id, user_name, created_at"

log = logging.getLogger("red.kirin-cogs.dashboard.modmail")


class Unavailable(Exception):
    """The modmail database is missing or can't be read."""


def classify(query: str) -> tuple[str, str | int]:
    """What a search means: ("all", ""), ("user", id), ("number", thread number) or ("text", query)."""
    query = query.strip()
    if not query:
        return "all", ""
    if re.fullmatch(r"\d{17,20}", query):
        return "user", query
    if match := re.fullmatch(r"#?(\d{1,16})", query):
        return "number", int(match[1])
    return "text", query


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _timestamp(value: object) -> float | None:
    try:
        return datetime.fromisoformat(str(value)).replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def _json(raw: object, kind: type) -> Any:
    try:
        value = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return kind()
    return value if isinstance(value, kind) else kind()


@contextlib.contextmanager
def _database() -> Iterator[sqlite3.Connection]:
    """A read-only connection for one short read. Blocking: use it inside asyncio.to_thread."""
    try:
        uri = f"{DB_PATH.absolute().as_uri()}?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            yield db
    except (sqlite3.Error, OSError) as exc:
        log.warning("Modmail database unavailable: %s", exc)
        raise Unavailable from exc


def _thread(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "number": row["thread_number"],
        "status": STATUS.get(row["status"], "Unknown"),
        "user_id": row["user_id"],
        "user_name": row["user_name"],
        "opened": _timestamp(row["created_at"]),
    }


def _embeds(metadata: dict) -> list[dict[str, str]]:
    embeds = []
    listed = [metadata.get(key) for key in ("embeds", "forwardedEmbeds")]
    for embed in [embed for group in listed if isinstance(group, list) for embed in group]:
        if isinstance(embed, dict):
            parts = {key: str(embed.get(key) or "") for key in ("title", "description", "url")}
            if any(parts.values()):
                embeds.append(parts)
    return embeds


def _message(row: sqlite3.Row) -> dict[str, Any]:
    metadata = _json(row["metadata"], dict)
    original = metadata.get("originalThreadMessage")
    original_body = str(original.get("body") or "") if isinstance(original, dict) else ""
    return {
        "kind": KINDS.get(row["message_type"], "system"),
        "name": row["user_name"],
        "role": row["role_name"] if row["is_anonymous"] else None,
        "body": row["body"] or "",
        "before": original_body,
        "after": str(metadata.get("newBody") or ""),
        "embeds": _embeds(metadata),
        "attachments": [a for a in _json(row["attachments"], list) if isinstance(a, str)],
        "when": _timestamp(row["created_at"]),
    }


def _list_threads(query: str, page: int) -> tuple[list[dict[str, Any]], bool]:
    kind, value = classify(query)
    where, params = {
        "all": ("1", ()),
        "user": ("user_id = ?", (value,)),
        "number": ("thread_number = ?", (value,)),
        # One pass over the messages: thread_messages has no index on thread_id, so EXISTS would scan per thread.
        "text": (
            "user_name LIKE ? ESCAPE '\\' OR id IN (SELECT thread_id FROM thread_messages WHERE body LIKE ? ESCAPE '\\')",
            (_like(str(value)), _like(str(value))),
        ),
    }[kind]
    sql = (
        f"SELECT {THREAD_COLUMNS} FROM threads WHERE {where} "
        "ORDER BY created_at DESC, thread_number DESC LIMIT ? OFFSET ?"
    )
    with _database() as db:
        rows = db.execute(sql, (*params, PAGE_SIZE + 1, page * PAGE_SIZE)).fetchall()
    return [_thread(row) for row in rows[:PAGE_SIZE]], len(rows) > PAGE_SIZE


def _get_thread(number: int) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    with _database() as db:
        row = db.execute(f"SELECT {THREAD_COLUMNS} FROM threads WHERE thread_number = ?", (number,)).fetchone()
        if row is None:
            return None
        messages = db.execute(
            "SELECT message_type, user_name, is_anonymous, role_name, body, attachments, metadata, created_at "
            "FROM thread_messages WHERE thread_id = ? ORDER BY created_at, id",
            (row["id"],),
        ).fetchall()
    return _thread(row), [_message(message) for message in messages]


def _threads_for_user(user_id: int) -> list[dict[str, Any]]:
    sql = f"SELECT {THREAD_COLUMNS} FROM threads WHERE user_id = ? ORDER BY created_at DESC LIMIT ?"
    with _database() as db:
        rows = db.execute(sql, (str(user_id), USER_THREADS)).fetchall()
    return [_thread(row) for row in rows]


async def list_threads(query: str, page: int) -> tuple[list[dict[str, Any]], bool]:
    """One page of threads, newest first, and whether an older page exists. Raises Unavailable."""
    return await asyncio.to_thread(_list_threads, query, page)


async def get_thread(number: int) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """The thread and its messages oldest first, or None if there is no such thread. Raises Unavailable."""
    return await asyncio.to_thread(_get_thread, number)


async def threads_for_user(user_id: int) -> list[dict[str, Any]]:
    """The user's latest threads, newest first. Raises Unavailable."""
    return await asyncio.to_thread(_threads_for_user, user_id)


def _path(url: str) -> str:
    return urlsplit(url).path


def _expires(url: str) -> float:
    """When a signed CDN link stops working (its hex `ex` parameter), minus a margin; 0 if it has none."""
    try:
        return int(parse_qs(urlsplit(url).query)["ex"][0], 16) - REFRESH_MARGIN
    except (KeyError, ValueError):
        return 0


class AttachmentLinks:
    """Freshly signed CDN links for stored attachment URLs, cached in memory until they expire."""

    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._cache: dict[str, tuple[str, float]] = {}  # stored URL -> (signed link, usable until)

    def clear(self) -> None:
        self._cache.clear()

    async def refresh(self, urls: list[str]) -> dict[str, str]:
        """Signed links for the Discord CDN URLs in `urls`; ones Discord refused or left out are missing."""
        now = time.time()
        fresh = {url: hit[0] for url in urls if (hit := self._cache.get(url)) and hit[1] > now}
        wanted = list(dict.fromkeys(url for url in urls if url.startswith(CDN) and url not in fresh))
        found: dict[str, tuple[str, float]] = {}
        for start in range(0, len(wanted), REFRESH_BATCH):
            batch = wanted[start : start + REFRESH_BATCH]
            try:
                data = await self.bot.http.request(
                    Route("POST", "/attachments/refresh-urls"), json={"attachment_urls": batch}
                )
            except (discord.HTTPException, aiohttp.ClientError, TimeoutError):
                log.warning("Discord refused to refresh %d attachment links", len(batch), exc_info=True)
                continue
            # Matched by path, in case Discord doesn't echo the query string exactly as sent.
            by_path = {
                _path(str(item.get("original", ""))): str(item.get("refreshed", ""))
                for item in (data or {}).get("refreshed_urls", [])
                if isinstance(item, dict) and str(item.get("refreshed", "")).startswith(CDN)
            }
            for url in batch:
                if link := by_path.get(_path(url)):
                    found[url] = (link, _expires(link))
        if found:
            self._cache = {url: hit for url, hit in self._cache.items() if hit[1] > now}
            self._cache.update({url: hit for url, hit in found.items() if hit[1] > now})
        return fresh | {url: hit[0] for url, hit in found.items()}


def _file(entry: str, links: dict[str, str]) -> dict[str, Any]:
    """How to show one stored attachment entry: a text note, an inline image, a file link, or unavailable."""
    if not entry.startswith(("https://", "http://")):
        return {"text": entry}
    name = _path(entry).rsplit("/", 1)[-1] or entry
    return {
        "name": name,
        "url": links.get(entry),
        "image": name.rsplit(".", 1)[-1].lower() in IMAGE_EXTENSIONS if "." in name else False,
    }


class StaffModmail:
    def __init__(self, cog: "Dashboard") -> None:
        self.cog = cog
        self.links = AttachmentLinks(cog.bot)

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get("/modmail", self.threads)
        app.router.add_get(r"/modmail/{number:\d{1,9}}", self.thread)

    def _render(self, request: web.Request, template: str, **context: Any) -> web.Response:
        return self.cog._render(request, f"modmail/{template}", **context)

    async def threads(self, request: web.Request) -> web.StreamResponse:
        from .dashboard import _page_number

        query = request.query.get("q", "").strip()[:MAX_QUERY]
        page = _page_number(request.query.get("page", "0"))
        try:
            threads, more = await list_threads(query, page)
        except Unavailable:
            return self._render(request, "threads.html", unavailable=True, q=query)
        return self._render(request, "threads.html", threads=threads, more=more, page=page, q=query)

    async def thread(self, request: web.Request) -> web.StreamResponse:
        try:
            found = await get_thread(int(request.match_info["number"]))
        except Unavailable:
            return self._render(request, "thread.html", unavailable=True)
        if found is None:
            return self.cog._message(request, 404, "Thread not found", "There is no modmail thread with that number.")
        thread, messages = found
        links = await self.links.refresh([url for message in messages for url in message["attachments"]])
        for message in messages:
            message["files"] = [_file(entry, links) for entry in message["attachments"]]
        return self._render(request, "thread.html", thread=thread, messages=messages)

    async def for_user(self, user_id: int) -> list[dict[str, Any]] | None:
        """The user's threads for the ban page, or None when modmail is unavailable."""
        try:
            return await threads_for_user(user_id)
        except Unavailable:
            return None
