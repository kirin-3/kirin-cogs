"""Claims are committed together with their payment, and transfers can't overwrite a newer owner."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.systems.waifu_system import WaifuSystem

USER = 31
BUYER = 32
NEW_OWNER = 33
WAIFU = 34


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "claims.db"))
    await manager.connect()
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()


def _failing_credit(db: DatabaseManager):
    return patch.object(db.economy, "_add_currency", new=AsyncMock(side_effect=RuntimeError("disk full")))


@pytest.mark.asyncio
async def test_failed_timely_credit_leaves_the_cooldown_unused(db: DatabaseManager) -> None:
    with _failing_credit(db), pytest.raises(RuntimeError):
        await db.economy.attempt_timely_claim(USER, 3600, lambda streak: 100)

    assert await db.economy.attempt_timely_claim(USER, 3600, lambda streak: 100) == 1
    assert await db.economy.get_user_currency(USER) == 100


@pytest.mark.asyncio
async def test_failed_rakeback_credit_keeps_the_balance(db: DatabaseManager) -> None:
    await db.economy.add_rakeback(USER, 50)

    with _failing_credit(db), pytest.raises(RuntimeError):
        await db.economy.claim_rakeback(USER)

    assert await db.economy.get_rakeback_balance(USER) == 50
    assert await db.economy.claim_rakeback(USER) == 50
    assert await db.economy.get_rakeback_balance(USER) == 0
    assert await db.economy.get_user_currency(USER) == 50


@pytest.mark.asyncio
async def test_transfer_does_not_overwrite_a_purchase_that_landed_first(db: DatabaseManager) -> None:
    await db.waifu.claim_waifu(WAIFU, USER, 1000)
    stale = await db.waifu.get_waifu_info(WAIFU)
    await db.economy.add_currency(BUYER, 10_000, "test")
    assert await db.waifu.force_claim_waifu(WAIFU, BUYER, USER, 1100, "claim", "sold")

    waifus = WaifuSystem(db, MagicMock(), MagicMock())
    # The owner's ownership check saw the snapshot from before the purchase
    with patch.object(db.waifu, "get_waifu_info", new=AsyncMock(return_value=stale)):
        ok, _ = await waifus.transfer_waifu(
            MagicMock(spec=discord.Member, id=USER),
            WAIFU,
            MagicMock(spec=discord.Member, id=NEW_OWNER, display_name="new"),
        )

    assert ok is False
    info = await db.waifu.get_waifu_info(WAIFU)
    assert info is not None
    assert info[1] == BUYER
