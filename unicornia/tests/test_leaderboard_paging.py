"""Database-level filtered economy leaderboard paging tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import discord
import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.systems.economy_system import EconomySystem


@pytest_asyncio.fixture
async def system(tmp_path: Path) -> AsyncGenerator[EconomySystem, None]:
    db = DatabaseManager(str(tmp_path / "leaderboard.db"))
    await db.connect()
    await db.initialize()
    async with db._get_connection() as connection:
        await connection.executemany(
            "INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)",
            ((user_id, 2_000 - user_id) for user_id in range(1, 1_201)),
        )
        await connection.commit()
    yield EconomySystem(db, MagicMock(), MagicMock())
    await db.close()


def _guild(*, excluded: set[int] | None = None) -> discord.Guild:
    excluded = excluded or set()
    members = [
        SimpleNamespace(id=user_id, bot=user_id in excluded)
        for user_id in range(1, 1_201)
        if user_id != 50  # non-member
    ]
    guild = MagicMock(spec=discord.Guild)
    guild.members = members
    return cast(discord.Guild, guild)


@pytest.mark.asyncio
async def test_page_beyond_old_thousand_row_ceiling_is_reachable(system: EconomySystem) -> None:
    page = await system.get_filtered_leaderboard(_guild(), limit=10, offset=1_000)

    assert len(page) == 10
    assert page[0][0] == 1_002  # user 50 is absent, so later ranks shift by one


@pytest.mark.asyncio
async def test_exclusions_refill_page_without_gaps(system: EconomySystem) -> None:
    page = await system.get_filtered_leaderboard(_guild(excluded={2, 3, 4}), limit=10, offset=0)

    assert len(page) == 10
    assert [user_id for user_id, _ in page] == [1, 5, 6, 7, 8, 9, 10, 11, 12, 13]


@pytest.mark.asyncio
async def test_forward_then_back_has_stable_ranks(system: EconomySystem) -> None:
    guild = _guild(excluded={2, 3})
    first = await system.get_filtered_leaderboard(guild, limit=10, offset=0)
    second = await system.get_filtered_leaderboard(guild, limit=10, offset=10)
    first_again = await system.get_filtered_leaderboard(guild, limit=10, offset=0)

    assert first_again == first
    assert not ({user_id for user_id, _ in first} & {user_id for user_id, _ in second})
    assert await system.get_filtered_leaderboard_rank(guild, second[0][0]) == 10
