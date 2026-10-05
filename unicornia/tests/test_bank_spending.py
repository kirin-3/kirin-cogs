"""Spending draws on the wallet first, then the bank, so members don't have to withdraw before buying or betting."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.db.economy import OUTCOME_INSUFFICIENT_FUNDS, OUTCOME_RESERVED

USER = 1001


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "unicornia.db"))
    await manager.connect()
    await manager.initialize()
    yield manager
    await manager.close()


async def _fund(db: DatabaseManager, wallet: int, bank: int) -> None:
    if wallet:
        await db.economy.add_currency(USER, wallet, "award")
    await db.economy.update_bank_balance(USER, bank)


async def _balances(db: DatabaseManager) -> tuple[int, int]:
    return await db.economy.get_user_currency(USER), await db.economy.get_bank_balance(USER)


@pytest.mark.asyncio
async def test_spending_empties_the_wallet_before_the_bank(db: DatabaseManager) -> None:
    await _fund(db, wallet=300, bank=1_000)

    assert await db.economy.get_spendable(USER) == 1_300
    assert await db.economy.remove_currency(USER, 200, "shop")
    assert await _balances(db) == (100, 1_000)
    assert await db.economy.remove_currency(USER, 500, "shop")
    assert await _balances(db) == (0, 600)


@pytest.mark.asyncio
async def test_spending_more_than_wallet_and_bank_changes_nothing(db: DatabaseManager) -> None:
    await _fund(db, wallet=300, bank=1_000)

    assert not await db.economy.remove_currency(USER, 1_301, "shop")
    assert await _balances(db) == (300, 1_000)
    assert not await db.economy.transfer_currency(USER, 2002, 1_301)
    assert await _balances(db) == (300, 1_000)


@pytest.mark.asyncio
async def test_a_bet_can_be_staked_from_the_bank(db: DatabaseManager) -> None:
    await _fund(db, wallet=0, bank=500)

    reserved = await db.economy.reserve_stake(key="bet-1", user_id=USER, amount=400, game="coinflip")
    assert reserved.state == OUTCOME_RESERVED
    assert await _balances(db) == (0, 100)

    refused = await db.economy.reserve_stake(key="bet-2", user_id=USER, amount=200, game="coinflip")
    assert refused.state == OUTCOME_INSUFFICIENT_FUNDS
    assert refused.new_balance == 100  # what they could spend, not just the empty wallet
    assert await _balances(db) == (0, 100)


@pytest.mark.asyncio
async def test_one_log_row_records_the_whole_payment(db: DatabaseManager) -> None:
    await _fund(db, wallet=100, bank=1_000)

    assert await db.economy.remove_currency(USER, 600, "shop_purchase", note="Role")
    async with db._get_connection() as conn:
        cursor = await conn.execute(
            "SELECT Amount, Type FROM CurrencyTransactions WHERE UserId = ? AND Type = 'shop_purchase'", (USER,)
        )
        assert [tuple(row) for row in await cursor.fetchall()] == [(-600, "shop_purchase")]


@pytest.mark.asyncio
async def test_an_xp_shop_item_can_be_bought_from_the_bank(db: DatabaseManager) -> None:
    await _fund(db, wallet=100, bank=1_000)

    assert await db.xp.purchase_xp_item(USER, 1, "bg", 600)
    assert await _balances(db) == (0, 500)
    assert await db.xp.user_owns_xp_item(USER, 1, "bg")


@pytest.mark.asyncio
async def test_a_refused_xp_shop_purchase_leaves_the_connection_usable(db: DatabaseManager) -> None:
    await _fund(db, wallet=100, bank=200)

    assert not await db.xp.purchase_xp_item(USER, 1, "bg", 301)
    assert db._conn is not None and not db._conn.in_transaction
    assert await db.economy.remove_currency(USER, 300, "shop")  # its BEGIN would fail on a dangling transaction
    assert await _balances(db) == (0, 0)
    assert not await db.xp.user_owns_xp_item(USER, 1, "bg")
