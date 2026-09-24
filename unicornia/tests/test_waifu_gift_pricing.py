"""Waifu gift prices are changed inside the transaction, so simultaneous gifts all count."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import MagicMock

import discord
import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.systems.waifu_system import WaifuSystem

GIVER = 11
OTHER_GIVER = 12
WAIFU = 21


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "waifu.db"))
    await manager.connect()
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
def waifus(db: DatabaseManager) -> WaifuSystem:
    return WaifuSystem(db, MagicMock(), MagicMock())


def _member(user_id: int) -> MagicMock:
    return MagicMock(spec=discord.Member, id=user_id, display_name=f"user{user_id}")


@pytest.mark.asyncio
async def test_simultaneous_gifts_all_raise_the_price(db: DatabaseManager, waifus: WaifuSystem) -> None:
    await db.economy.add_currency(GIVER, 10_000, "test")
    await db.economy.add_currency(OTHER_GIVER, 10_000, "test")
    await db.waifu.claim_waifu(WAIFU, GIVER, 1000)

    results = await asyncio.gather(
        waifus.gift_waifu(_member(GIVER), _member(WAIFU), "Rose"),
        waifus.gift_waifu(_member(OTHER_GIVER), _member(WAIFU), "Chocolate"),
    )

    assert all(ok for ok, _ in results)
    # Rose adds 225 and Chocolate 900; neither overwrites the other
    assert await db.waifu.get_waifu_price(WAIFU) == 1000 + 225 + 900
    assert len(await db.waifu.get_waifu_items(WAIFU)) == 2


@pytest.mark.asyncio
async def test_gift_reply_shows_the_stored_price(db: DatabaseManager, waifus: WaifuSystem) -> None:
    await db.economy.add_currency(GIVER, 10_000, "test")

    ok, reply = await waifus.gift_waifu(_member(GIVER), _member(WAIFU), "Rose")

    # A waifu with no record starts at 50
    assert ok
    assert await db.waifu.get_waifu_price(WAIFU) == 275
    assert reply.endswith("Their price increased by 225 to 275.")


@pytest.mark.asyncio
async def test_negative_gifts_never_take_the_price_below_one(db: DatabaseManager, waifus: WaifuSystem) -> None:
    await db.economy.add_currency(GIVER, 10_000, "test")
    await db.waifu.claim_waifu(WAIFU, GIVER, 60)

    await asyncio.gather(*(waifus.gift_waifu(_member(GIVER), _member(WAIFU), "Potato") for _ in range(3)))

    assert await db.waifu.get_waifu_price(WAIFU) == 1
    assert await db.economy.get_user_currency(GIVER) == 10_000 - 3 * 50


@pytest.mark.asyncio
async def test_gift_without_enough_currency_changes_nothing(db: DatabaseManager, waifus: WaifuSystem) -> None:
    await db.economy.add_currency(GIVER, 100, "test")
    await db.waifu.claim_waifu(WAIFU, GIVER, 1000)

    ok, reply = await waifus.gift_waifu(_member(GIVER), _member(WAIFU), "Rose")

    assert not ok
    assert "Not enough currency" in reply
    assert await db.waifu.get_waifu_price(WAIFU) == 1000
    assert await db.economy.get_user_currency(GIVER) == 100
