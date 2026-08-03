"""Real-database tests for Unicornia's idempotent economy operations.

Covers the additive schema (2.1), the atomic operation API (2.2), stake
reservation/settlement (2.3), and concurrency/fault-injection behavior (2.5).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.db.economy import (
    OUTCOME_DUPLICATE,
    OUTCOME_INSUFFICIENT_FUNDS,
    OUTCOME_NOT_FOUND,
    OUTCOME_RESERVED,
    OUTCOME_SETTLED,
)

USER = 1001


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "unicornia.db"))
    await manager.connect()
    await manager.initialize()
    yield manager
    await manager.close()


async def _log_rows(db: DatabaseManager, user_id: int = USER) -> list[tuple]:
    async with db._get_connection() as conn:
        cursor = await conn.execute(
            "SELECT UserId, Amount, Type, Extra, Reason FROM CurrencyTransactions WHERE UserId = ? ORDER BY Id",
            (user_id,),
        )
        return [tuple(row) for row in await cursor.fetchall()]


async def _table_info(db: DatabaseManager, table: str) -> list[tuple]:
    async with db._get_connection() as conn:
        cursor = await conn.execute(f"PRAGMA table_info({table})")
        return [tuple(row) for row in await cursor.fetchall()]


# ---------------------------------------------------------------------------
# 2.1 Schema and migration coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_db_has_economy_operations_table(db: DatabaseManager) -> None:
    columns = {row[1] for row in await _table_info(db, "EconomyOperations")}
    assert {
        "Id",
        "OperationKey",
        "GuildId",
        "UserId",
        "Source",
        "Direction",
        "Amount",
        "State",
        "Result",
        "CreatedAt",
        "SettledAt",
    } <= columns


@pytest.mark.asyncio
async def test_operation_key_is_unique(db: DatabaseManager) -> None:
    outcome = await db.economy.apply_operation(
        key="k1", user_id=USER, amount=10, direction="credit", source="test", transaction_type="test"
    )
    assert outcome.state == OUTCOME_SETTLED

    async with db._get_connection() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            await conn.execute(
                "INSERT INTO EconomyOperations (OperationKey, UserId, Source, Direction, Amount, State)"
                " VALUES ('k1', ?, 'test', 'credit', 1, 'settled')",
                (USER,),
            )


@pytest.mark.asyncio
async def test_initialize_migrates_legacy_db_and_is_idempotent(tmp_path: Path) -> None:
    """A pre-existing DB without the new table gains it; re-init keeps data."""
    manager = DatabaseManager(str(tmp_path / "legacy.db"))
    await manager.connect()
    await manager.initialize()

    # Simulate a legacy database that predates EconomyOperations.
    async with manager._get_connection() as conn:
        await conn.execute("DROP TABLE EconomyOperations")
        await conn.commit()

    await manager.initialize()
    assert await _table_info(manager, "EconomyOperations") != []

    # Existing rows survive re-initialization (additive, rollback-safe).
    await manager.economy.apply_operation(
        key="keep", user_id=USER, amount=5, direction="credit", source="test", transaction_type="test"
    )
    await manager.initialize()
    await manager.initialize()
    op = await manager.economy.get_operation("keep")
    assert op is not None
    assert op["State"] == "settled"
    await manager.close()


# ---------------------------------------------------------------------------
# 2.2 Atomic apply_operation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_credit_settles_with_one_log_row(db: DatabaseManager) -> None:
    outcome = await db.economy.apply_operation(
        key="credit-1",
        user_id=USER,
        amount=250,
        direction="credit",
        source="nitroaward",
        transaction_type="award",
        guild_id=42,
        note="Boost reward",
        result={"awarded": 250},
    )
    assert outcome.state == OUTCOME_SETTLED
    assert outcome.new_balance == 250

    op = await db.economy.get_operation("credit-1")
    assert op is not None
    assert op["State"] == "settled"
    assert op["GuildId"] == 42
    assert op["SettledAt"] is not None

    rows = await _log_rows(db)
    assert len(rows) == 1
    assert rows[0][1] == 250  # signed amount


@pytest.mark.asyncio
async def test_apply_duplicate_key_returns_original_without_effects(db: DatabaseManager) -> None:
    first = await db.economy.apply_operation(
        key="dup-1",
        user_id=USER,
        amount=100,
        direction="credit",
        source="patron",
        transaction_type="award",
        result={"original": True},
    )
    assert first.state == OUTCOME_SETTLED

    second = await db.economy.apply_operation(
        key="dup-1",
        user_id=USER,
        amount=100,
        direction="credit",
        source="patron",
        transaction_type="award",
    )
    assert second.state == OUTCOME_DUPLICATE
    assert second.existing_state == "settled"
    assert second.result == {"original": True}
    assert second.new_balance == 100

    assert len(await _log_rows(db)) == 1


@pytest.mark.asyncio
async def test_apply_debit_insufficient_funds_rolls_back_key_claim(db: DatabaseManager) -> None:
    outcome = await db.economy.apply_operation(
        key="debit-1", user_id=USER, amount=500, direction="debit", source="shop", transaction_type="shop"
    )
    assert outcome.state == OUTCOME_INSUFFICIENT_FUNDS
    assert outcome.new_balance == 0

    # Key claim rolled back: no operation row, no log row, safe to retry.
    assert await db.economy.get_operation("debit-1") is None
    assert await _log_rows(db) == []

    await db.economy.add_currency(USER, 600, "test", "test")
    retry = await db.economy.apply_operation(
        key="debit-1", user_id=USER, amount=500, direction="debit", source="shop", transaction_type="shop"
    )
    assert retry.state == OUTCOME_SETTLED
    assert retry.new_balance == 100


@pytest.mark.asyncio
async def test_apply_rolls_back_all_steps_on_failure(db: DatabaseManager) -> None:
    """A failing log insert rolls back balance, key claim, and log writes."""
    with pytest.raises(sqlite3.IntegrityError):
        await db.economy.apply_operation(
            key="fail-1",
            user_id=USER,
            amount=100,
            direction="credit",
            source="test",
            # None violates CurrencyTransactions.Type NOT NULL: fault injection.
            transaction_type=cast(str, None),
        )

    assert await db.economy.get_user_currency(USER) == 0
    assert await db.economy.get_operation("fail-1") is None
    assert await _log_rows(db) == []

    # The same key remains safe to retry after the failure.
    retry = await db.economy.apply_operation(
        key="fail-1", user_id=USER, amount=100, direction="credit", source="test", transaction_type="test"
    )
    assert retry.state == OUTCOME_SETTLED


# ---------------------------------------------------------------------------
# 2.3 Stake reservation and one-time settlement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reserve_and_settle_win(db: DatabaseManager) -> None:
    await db.economy.add_currency(USER, 1000, "test", "test")
    await _drain_setup_log(db)

    reserved = await db.economy.reserve_stake(key="bj-1", user_id=USER, amount=100, game="blackjack")
    assert reserved.state == OUTCOME_RESERVED
    assert reserved.new_balance == 900

    settled = await db.economy.settle_stake(
        key="bj-1", payout=250, transaction_type="blackjack", note="Blackjack win", result={"hand": 21}
    )
    assert settled.state == OUTCOME_SETTLED
    assert settled.new_balance == 1150

    # Exactly two canonical rows: stake out, payout in.
    rows = await _log_rows(db)
    assert [r[1] for r in rows] == [-100, 250]

    # Retry returns the original result with no further effects.
    retry = await db.economy.settle_stake(key="bj-1", payout=250, transaction_type="blackjack")
    assert retry.state == OUTCOME_DUPLICATE
    assert retry.result == {"hand": 21}
    assert retry.new_balance == 1150
    assert len(await _log_rows(db)) == 2


@pytest.mark.asyncio
async def test_settle_loss_writes_no_payout_row(db: DatabaseManager) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await _drain_setup_log(db)

    await db.economy.reserve_stake(key="slots-1", user_id=USER, amount=100, game="slots")
    settled = await db.economy.settle_stake(key="slots-1", payout=0, transaction_type="slots", note="Slots loss")
    assert settled.state == OUTCOME_SETTLED
    assert settled.new_balance == 400

    rows = await _log_rows(db)
    assert [r[1] for r in rows] == [-100]


@pytest.mark.asyncio
async def test_settle_refund_restores_stake(db: DatabaseManager) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await _drain_setup_log(db)

    await db.economy.reserve_stake(key="mines-1", user_id=USER, amount=100, game="mines")
    op = await db.economy.get_operation("mines-1")
    assert op is not None and op["State"] == "reserved"

    refund = await db.economy.settle_stake(key="mines-1", payout=100, transaction_type="mines", note="Mines refund")
    assert refund.state == OUTCOME_SETTLED
    assert refund.new_balance == 500


@pytest.mark.asyncio
async def test_settle_unknown_key_is_not_found(db: DatabaseManager) -> None:
    outcome = await db.economy.settle_stake(key="ghost", payout=100, transaction_type="test")
    assert outcome.state == OUTCOME_NOT_FOUND


@pytest.mark.asyncio
async def test_reserve_insufficient_funds_cannot_produce_winnings(db: DatabaseManager) -> None:
    await db.economy.add_currency(USER, 50, "test", "test")
    await _drain_setup_log(db)

    outcome = await db.economy.reserve_stake(key="poor-1", user_id=USER, amount=100, game="slots")
    assert outcome.state == OUTCOME_INSUFFICIENT_FUNDS
    assert await db.economy.get_operation("poor-1") is None

    # A failed reservation left nothing settleable behind.
    settle = await db.economy.settle_stake(key="poor-1", payout=999, transaction_type="slots")
    assert settle.state == OUTCOME_NOT_FOUND
    assert await db.economy.get_user_currency(USER) == 50


@pytest.mark.asyncio
async def test_restart_safe_settlement(tmp_path: Path) -> None:
    """A reserved operation is reconciled and refunded during restart."""
    manager = DatabaseManager(str(tmp_path / "restart.db"))
    await manager.connect()
    await manager.initialize()
    await manager.economy.add_currency(USER, 500, "test", "test")
    await manager.economy.reserve_stake(key="game-9", user_id=USER, amount=100, game="mines")
    await manager.close()

    # "Restart": new manager on the same database file.
    manager2 = DatabaseManager(str(tmp_path / "restart.db"))
    await manager2.connect()
    await manager2.initialize()
    op = await manager2.economy.get_operation("game-9")
    assert op is not None and op["State"] == "settled"
    assert await manager2.economy.get_user_currency(USER) == 500

    settled = await manager2.economy.settle_stake(key="game-9", payout=100, transaction_type="mines", note="refund")
    assert settled.state == OUTCOME_DUPLICATE
    assert settled.new_balance == 500
    await manager2.close()


async def _drain_setup_log(db: DatabaseManager) -> None:
    """Remove log rows created while arranging test balances."""
    async with db._get_connection() as conn:
        await conn.execute("DELETE FROM CurrencyTransactions")
        await conn.commit()


# ---------------------------------------------------------------------------
# 2.5 Concurrency and fault injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_reservations_only_affordable_succeed(db: DatabaseManager) -> None:
    await db.economy.add_currency(USER, 100, "test", "test")

    outcomes = await asyncio.gather(
        *(db.economy.reserve_stake(key=f"race-{i}", user_id=USER, amount=30, game="slots") for i in range(5))
    )
    states = sorted(o.state for o in outcomes)
    assert states.count(OUTCOME_RESERVED) == 3  # 100 // 30
    assert states.count(OUTCOME_INSUFFICIENT_FUNDS) == 2
    assert await db.economy.get_user_currency(USER) == 10


@pytest.mark.asyncio
async def test_concurrent_same_key_reservation_settles_once(db: DatabaseManager) -> None:
    await db.economy.add_currency(USER, 100, "test", "test")

    outcomes = await asyncio.gather(
        *(db.economy.reserve_stake(key="same-key", user_id=USER, amount=30, game="slots") for _ in range(2))
    )
    states = sorted(o.state for o in outcomes)
    assert states == [OUTCOME_DUPLICATE, OUTCOME_RESERVED]
    assert await db.economy.get_user_currency(USER) == 70


@pytest.mark.asyncio
async def test_concurrent_settlement_pays_out_once(db: DatabaseManager) -> None:
    await db.economy.add_currency(USER, 100, "test", "test")
    await db.economy.reserve_stake(key="settle-race", user_id=USER, amount=50, game="blackjack")

    outcomes = await asyncio.gather(
        *(db.economy.settle_stake(key="settle-race", payout=150, transaction_type="blackjack") for _ in range(2))
    )
    states = sorted(o.state for o in outcomes)
    assert states == [OUTCOME_DUPLICATE, OUTCOME_SETTLED]
    # Stake deducted once, payout credited once.
    assert await db.economy.get_user_currency(USER) == 200


@pytest.mark.asyncio
async def test_concurrent_duplicate_key_apply_logs_one_row(db: DatabaseManager) -> None:
    outcomes = await asyncio.gather(
        *(
            db.economy.apply_operation(
                key="boost-1",
                user_id=USER,
                amount=500,
                direction="credit",
                source="nitroaward",
                transaction_type="award",
            )
            for _ in range(3)
        )
    )
    states = [o.state for o in outcomes]
    assert states.count(OUTCOME_SETTLED) == 1
    assert states.count(OUTCOME_DUPLICATE) == 2
    assert await db.economy.get_user_currency(USER) == 500
    assert len(await _log_rows(db)) == 1
