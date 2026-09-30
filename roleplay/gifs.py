"""The roleplay gifs for the member site: paging an action's pools, and members' thumbs up and down.

The gifs are the files in the images folder, listed each time they're asked for, so the site shows the folder as it
is. A gif is its action and filename; a request's name is only ever looked up in that listing, never joined onto a path.
Votes are stored per gif: ``{"votes": {user ID: 1 or -1}}``. A vote for a file that has since gone stays in storage
and is never shown, so swapping the folder doesn't wipe the votes.
"""

import asyncio
import os
from collections.abc import Sequence
from io import BufferedIOBase
from pathlib import Path
from typing import TypeVar

from redbot.core import Config

from .actions import image_files

T = TypeVar("T")

# gifs on one page of the member site
PAGE_SIZE = 5


def page_of(items: Sequence[T], page: int, size: int) -> tuple[list[T], int, int]:
    """One page (1-based, clamped to the last) of ``items``, the page number shown, and how many pages there are."""
    pages = max(1, -(-len(items) // size))
    page = min(max(page, 1), pages)
    start = (page - 1) * size
    return list(items[start : start + size]), page, pages


def gifs_of(folder: Path) -> dict[str, Path]:
    """An action's images by filename, in filename order. If two subfolders hold the same name, the first one wins."""
    found: dict[str, Path] = {}
    for file in image_files(folder):
        found.setdefault(file.name, file)
    return found


def gif_info(fp: BufferedIOBase) -> tuple[bool, int]:
    """Whether the file starts like a GIF (judged by its content, not its name), and its size. Leaves it at the start."""
    fp.seek(0)
    head = fp.read(6)
    size = fp.seek(0, os.SEEK_END)
    fp.seek(0)
    return head in (b"GIF87a", b"GIF89a"), size


def _valid_votes(record: object) -> dict[str, int]:
    """The good votes in a stored record; anything malformed is left out."""
    votes = record.get("votes") if isinstance(record, dict) else None
    if not isinstance(votes, dict):
        return {}
    return {
        user_id: value
        for user_id, value in votes.items()
        if isinstance(user_id, str) and user_id.isdigit() and type(value) is int and value in (1, -1)
    }


class GifVotes:
    def __init__(self, config: Config) -> None:
        self.config = config
        config.init_custom("GIF_VOTES", 2)  # action, filename
        config.register_custom("GIF_VOTES", votes={})
        # ponytail: one lock for every gif; a vote is a single click, so contention is tiny
        self.lock = asyncio.Lock()

    async def _store(self, action: str, name: str, votes: dict[str, int]) -> None:
        record = self.config.custom("GIF_VOTES", action, name)
        if votes:
            await record.votes.set(votes)
        else:
            await record.clear()

    async def set(self, user_id: int, action: str, name: str, value: int) -> None:
        """The member's vote on a gif: 1 (up), -1 (down), or 0 to take it back."""
        if value not in (1, -1, 0):
            raise ValueError(f"{value!r} isn't a vote.")
        async with self.lock:
            votes = _valid_votes(await self.config.custom("GIF_VOTES", action, name).all())
            if value:
                votes[str(user_id)] = value
            else:
                votes.pop(str(user_id), None)
            await self._store(action, name, votes)

    async def mine(self, user_id: int, action: str, names: Sequence[str]) -> dict[str, int]:
        """The member's own vote on each of these gifs; the ones they haven't voted on are left out."""
        found: dict[str, int] = {}
        for name in names:
            votes = _valid_votes(await self.config.custom("GIF_VOTES", action, name).all())
            if str(user_id) in votes:
                found[name] = votes[str(user_id)]
        return found

    async def totals(self) -> dict[tuple[str, str], tuple[int, int]]:
        """(up, down) for every gif with at least one vote, by (action, filename)."""
        found: dict[tuple[str, str], tuple[int, int]] = {}
        for action, records in (await self.config.custom("GIF_VOTES").all()).items():
            if not isinstance(records, dict):
                continue
            for name, record in records.items():
                votes = _valid_votes(record)
                if votes:
                    up = sum(value == 1 for value in votes.values())
                    found[action, name] = (up, len(votes) - up)
        return found

    async def forget(self, user_id: int) -> None:
        """Delete every vote the user has cast."""
        key = str(user_id)
        async with self.lock:
            for action, records in (await self.config.custom("GIF_VOTES").all()).items():
                if not isinstance(records, dict):
                    continue
                for name, record in records.items():
                    raw = record.get("votes") if isinstance(record, dict) else None
                    if isinstance(raw, dict) and key in raw:
                        rest = {k: v for k, v in _valid_votes(record).items() if k != key}
                        await self._store(action, name, rest)
