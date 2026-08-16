"""Stock position-unwind planning and execution coverage."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from redbot.core.commands.requires import PrivilegeLevel

from unicornia.commands.stock import StockCommands, format_unwind_outcome
from unicornia.database import DatabaseManager
from unicornia.stock_market import INITIAL_SHARE_RESERVE, P_BASE, plan_stock_unwind
from unicornia.systems.market_system import MarketSystem

USER_A = 7101
USER_B = 7102


@pytest_asyncio.fixture
async def market(tmp_path: Path) -> AsyncGenerator[MarketSystem, None]:
    db = DatabaseManager(str(tmp_path / "unwind.db"))
    await db.connect()
    await db.initialize()
    await db.stock.create_stock("ABC", "Example", "📈", 250)
    config = MagicMock()
    config.currency_symbol = AsyncMock(return_value="$")
    system = MarketSystem(db, config, MagicMock(guilds=[]), MagicMock())
    await system.initialize()
    system.update_dashboard = AsyncMock()
    yield system
    await db.close()


async def _seed_holding(
    db: DatabaseManager,
    *,
    user_id: int,
    symbol: str = "ABC",
    amount: int = 10,
    average_cost: float = 50.0,
) -> None:
    async with db._get_connection() as connection:
        await connection.execute(
            "INSERT OR REPLACE INTO StockHoldings (UserId, Symbol, Amount, AverageCost) VALUES (?, ?, ?, ?)",
            (user_id, symbol, amount, average_cost),
        )
        await connection.execute(
            "UPDATE Stocks SET TotalShares = TotalShares + ?, ShareReserve = ShareReserve - ? WHERE Symbol = ?",
            (amount, amount, symbol),
        )
        await connection.commit()


async def _snapshot(db: DatabaseManager) -> tuple[list[tuple], list[tuple], list[tuple], str | None]:
    async with db._get_connection() as connection:
        users = await (
            await connection.execute("SELECT UserId, CurrencyAmount FROM DiscordUser ORDER BY UserId")
        ).fetchall()
        holdings = await (
            await connection.execute(
                "SELECT UserId, Symbol, Amount, AverageCost FROM StockHoldings ORDER BY UserId, Symbol"
            )
        ).fetchall()
        stocks = await (
            await connection.execute(
                "SELECT Symbol, CurrentPrice, PreviousPrice, TotalShares, ShareReserve FROM Stocks ORDER BY Symbol"
            )
        ).fetchall()
    return (
        [tuple(row) for row in users],
        [tuple(row) for row in holdings],
        [tuple(row) for row in stocks],
        await db.stock.get_unwind_run_id(),
    )


def test_planner_uses_recorded_basis_and_ignores_market_price() -> None:
    plan = plan_stock_unwind(
        [{"user_id": USER_A, "symbol": "ABC", "amount": 2, "average_cost": 50.25, "current_price": 1e9}],
        [],
    )
    assert plan.total_refund == round(2 * 50.25)
    assert plan.refunds[0].per_share_cost == 50.25


def test_planner_uses_blended_basis_for_remaining_partial_position() -> None:
    plan = plan_stock_unwind(
        [{"user_id": USER_A, "symbol": "ABC", "amount": 50, "average_cost": 75.0}],
        [],
    )
    assert plan.total_refund == 3_750


def test_planner_falls_back_to_trade_ledger() -> None:
    ledger = [
        {
            "user_id": USER_A,
            "symbol": "ABC",
            "side": "buy",
            "kind": "trade",
            "shares": 100,
            "exec_price": 99.0,
            "tax": 100,
            "total_amount": -10_000,
        },
        {
            "user_id": USER_A,
            "symbol": "ABC",
            "side": "sell",
            "kind": "trade",
            "shares": 50,
            "exec_price": 1_000_000.0,
            "tax": 0,
            "total_amount": 50_000_000,
        },
    ]
    plan = plan_stock_unwind([{"user_id": USER_A, "symbol": "ABC", "amount": 50, "average_cost": 0.0}], ledger)
    assert plan.total_refund == 5_000
    assert plan.unresolvable == ()


def test_planner_reports_unresolvable_import_with_repair_details() -> None:
    plan = plan_stock_unwind(
        [{"user_id": USER_A, "symbol": "ABC", "amount": 7, "average_cost": None}],
        [
            {
                "user_id": USER_A,
                "symbol": "ABC",
                "side": "buy",
                "kind": "trade",
                "shares": 7,
                "exec_price": 0.0,
                "tax": 0,
                "total_amount": -100,
                "imported": True,
            }
        ],
    )
    assert plan.refunds == ()
    assert (plan.unresolvable[0].user_id, plan.unresolvable[0].symbol, plan.unresolvable[0].shares) == (
        USER_A,
        "ABC",
        7,
    )


@pytest.mark.asyncio
async def test_dry_run_is_pure_and_matches_confirmed_refund(market: MarketSystem) -> None:
    await _seed_holding(market.db, user_id=USER_A, amount=10, average_cost=50.0)
    before = await _snapshot(market.db)
    dry_run = await market.unwind_market()
    assert await _snapshot(market.db) == before

    confirmed = await market.unwind_market(confirm=True)
    assert confirmed.executed
    assert confirmed.plan.total_refund == dry_run.plan.total_refund == 500
    assert await market.db.economy.get_user_currency(USER_A) == 500


def test_unwind_command_is_owner_only() -> None:
    command = cast(Any, StockCommands.stock_unwind)
    assert command.requires.privilege_level is PrivilegeLevel.BOT_OWNER


@pytest.mark.asyncio
async def test_interrupted_run_resumes_without_double_credit(market: MarketSystem, monkeypatch) -> None:
    await _seed_holding(market.db, user_id=USER_A, amount=10, average_cost=50.0)
    original_close = market.db.stock.close_unwound_holding
    first_attempt = True

    async def interrupt_once(**kwargs):
        nonlocal first_attempt
        if first_attempt:
            first_attempt = False
            raise RuntimeError("simulated interruption")
        return await original_close(**kwargs)

    monkeypatch.setattr(market.db.stock, "close_unwound_holding", interrupt_once)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        await market.unwind_market(confirm=True)
    persisted_run = await market.db.stock.get_unwind_run_id()
    assert persisted_run is not None
    assert await market.db.economy.get_user_currency(USER_A) == 500

    resumed = await market.unwind_market(confirm=True)
    assert resumed.executed and resumed.run_id == persisted_run
    assert await market.db.economy.get_user_currency(USER_A) == 500
    async with market.db._get_connection() as connection:
        currency_rows = await (
            await connection.execute(
                "SELECT COUNT(*) FROM CurrencyTransactions WHERE UserId = ? AND Type = 'stock_unwind'",
                (USER_A,),
            )
        ).fetchone()
        ledger_rows = await (
            await connection.execute(
                "SELECT COUNT(*) FROM StockTransactions WHERE UserId = ? AND Side = 'sell' AND Kind = 'unwind'",
                (USER_A,),
            )
        ).fetchone()
    assert currency_rows is not None and ledger_rows is not None
    assert currency_rows[0] == ledger_rows[0] == 1


@pytest.mark.asyncio
async def test_interruption_after_final_holding_resumes_market_reset(market: MarketSystem, monkeypatch) -> None:
    await _seed_holding(market.db, user_id=USER_A, amount=10, average_cost=50.0)
    original_reset = market.db.stock.reset_market
    first_attempt = True

    async def interrupt_once() -> None:
        nonlocal first_attempt
        if first_attempt:
            first_attempt = False
            raise RuntimeError("simulated interruption before reset")
        await original_reset()

    monkeypatch.setattr(market.db.stock, "reset_market", interrupt_once)
    with pytest.raises(RuntimeError, match="simulated interruption before reset"):
        await market.unwind_market(confirm=True)

    persisted_run = await market.db.stock.get_unwind_run_id()
    stock_before_resume = await market.db.stock.get_stock("ABC")
    assert persisted_run is not None and stock_before_resume is not None
    assert await market.db.stock.get_holding(USER_A, "ABC") is None
    assert stock_before_resume["total_shares"] == 10

    resumed = await market.unwind_market(confirm=True)
    stock_after_resume = await market.db.stock.get_stock("ABC")
    assert resumed.executed and resumed.run_id == persisted_run
    assert stock_after_resume is not None
    assert stock_after_resume["total_shares"] == 0
    assert stock_after_resume["share_reserve"] == INITIAL_SHARE_RESERVE
    assert stock_after_resume["price"] == stock_after_resume["previous_price"] == P_BASE
    assert await market.db.stock.get_unwind_run_id() is None
    assert await market.db.economy.get_user_currency(USER_A) == 500

    async with market.db._get_connection() as connection:
        currency_rows = await (
            await connection.execute(
                "SELECT COUNT(*) FROM CurrencyTransactions WHERE UserId = ? AND Type = 'stock_unwind'",
                (USER_A,),
            )
        ).fetchone()
        ledger_rows = await (
            await connection.execute(
                "SELECT COUNT(*) FROM StockTransactions WHERE UserId = ? AND Side = 'sell' AND Kind = 'unwind'",
                (USER_A,),
            )
        ).fetchone()
    assert currency_rows is not None and ledger_rows is not None
    assert currency_rows[0] == ledger_rows[0] == 1


@pytest.mark.asyncio
async def test_later_run_uses_fresh_identifier(market: MarketSystem) -> None:
    await _seed_holding(market.db, user_id=USER_A, amount=2, average_cost=10.0)
    first = await market.unwind_market(confirm=True)
    await _seed_holding(market.db, user_id=USER_A, amount=3, average_cost=10.0)
    second = await market.unwind_market(confirm=True)
    assert first.executed and second.executed
    assert first.run_id != second.run_id
    assert await market.db.economy.get_user_currency(USER_A) == 50


@pytest.mark.asyncio
async def test_unwind_audit_rows_are_distinct_and_hidden_from_trade_history(market: MarketSystem) -> None:
    await _seed_holding(market.db, user_id=USER_A, amount=4, average_cost=12.5)
    await market.unwind_market(confirm=True)
    history = await market.db.stock.get_transactions(USER_A)
    holdings, trading_history = await market.get_portfolio_data(USER_A)
    assert holdings == []
    assert history[0]["action"] == "Unwound"
    assert history[0]["kind"] == "unwind"
    assert trading_history == {}


@pytest.mark.asyncio
async def test_trade_waits_for_market_lock(market: MarketSystem) -> None:
    await market.db.economy.add_currency(USER_A, 10_000, "test", "test")
    await market.lock.acquire()
    trade = asyncio.create_task(market.buy_stock(SimpleNamespace(id=USER_A), "ABC", 1))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    assert not trade.done()
    market.lock.release()
    success, _ = await trade
    assert success


@pytest.mark.asyncio
async def test_successful_unwind_leaves_flat_market(market: MarketSystem) -> None:
    await _seed_holding(market.db, user_id=USER_A, amount=4, average_cost=12.5)
    outcome = await market.unwind_market(confirm=True)
    stock = await market.db.stock.get_stock("ABC")
    assert outcome.executed and stock is not None
    assert await market.db.stock.get_holding(USER_A, "ABC") is None
    assert stock["total_shares"] == 0
    assert stock["share_reserve"] == INITIAL_SHARE_RESERVE
    assert stock["price"] == stock["previous_price"] == P_BASE
    market.update_dashboard.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_empty_market_reports_nothing_and_changes_nothing(market: MarketSystem) -> None:
    before = await _snapshot(market.db)
    outcome = await market.unwind_market(confirm=True)
    message = format_unwind_outcome(outcome, confirmed=True)
    assert not outcome.executed and not outcome.aborted
    assert outcome.plan.refunds == outcome.plan.unresolvable == ()
    assert await _snapshot(market.db) == before
    assert "No Changes Needed" in message
    assert "Dry Run" not in message
    assert "unwind confirm" not in message


@pytest.mark.asyncio
async def test_unresolvable_plan_aborts_before_every_mutation_then_repair_unblocks(market: MarketSystem) -> None:
    await market.db.stock.create_stock("BAD", "Broken", "⚠️", 999)
    await _seed_holding(market.db, user_id=USER_A, symbol="ABC", amount=2, average_cost=50.0)
    await _seed_holding(market.db, user_id=USER_B, symbol="BAD", amount=1, average_cost=0.0)
    await market.initialize()
    before = await _snapshot(market.db)

    aborted = await market.unwind_market(confirm=True)
    assert aborted.aborted and not aborted.executed
    assert len(aborted.plan.refunds) == len(aborted.plan.unresolvable) == 1
    assert await _snapshot(market.db) == before
    assert await market.db.stock.get_unwind_run_id() is None
    async with market.db._get_connection() as connection:
        row = await (
            await connection.execute("SELECT COUNT(*) FROM CurrencyTransactions WHERE Type = 'stock_unwind'")
        ).fetchone()
        await connection.execute(
            "UPDATE StockHoldings SET AverageCost = 75 WHERE UserId = ? AND Symbol = 'BAD'",
            (USER_B,),
        )
        await connection.commit()
    assert row is not None and row[0] == 0

    repaired = await market.unwind_market(confirm=True)
    assert repaired.executed and not repaired.aborted
    assert repaired.plan.total_refund == 175
    assert await market.db.stock.get_holding(USER_A, "ABC") is None
    assert await market.db.stock.get_holding(USER_B, "BAD") is None
    for symbol in ("ABC", "BAD"):
        stock = await market.db.stock.get_stock(symbol)
        assert stock is not None
        assert stock["total_shares"] == 0
        assert stock["share_reserve"] == INITIAL_SHARE_RESERVE
        assert stock["price"] == P_BASE
