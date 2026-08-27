"""Regression coverage for the yield pool, pooled wagering, and dividends."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from redbot.core.commands.requires import PrivilegeLevel

from unicornia.commands.admin import AdminCommands
from unicornia.database import DatabaseManager
from unicornia.gambling import RAKEBACK_RATE, RTP_TARGET, pooled_rake
from unicornia.systems.yield_system import YieldSystem


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(
        str(tmp_path / "yield.db"),
        reconcile_reserved_on_initialize=False,
    )
    await manager.connect()
    await manager.initialize()
    yield manager
    await manager.close()


async def _fund(db: DatabaseManager, user_id: int, amount: int = 10_000) -> None:
    await db.economy.add_currency(user_id, amount, "test", "test")


@pytest.mark.asyncio
async def test_schema_upgrade_is_idempotent_and_preserves_existing_totals(db: DatabaseManager) -> None:
    async with db._get_connection() as connection:
        await connection.execute(
            "INSERT INTO GamblingStats (Feature, BetAmount, WinAmount, LossAmount) VALUES ('legacy', 10, 20, 30)"
        )
        await connection.execute(
            """
            INSERT INTO Stocks
                (Symbol, Name, Emoji, CurrentPrice, PreviousPrice, TotalShares, SmoothedUsage, PeriodUsage)
            VALUES ('OLD', 'Old', ':old:', 10, 9, 5, 7.5, 11)
            """
        )
        await connection.commit()
        await db._update_database_schema(connection)
        await db._update_database_schema(connection)
        gambling_columns = {
            row[1] for row in await (await connection.execute("PRAGMA table_info(GamblingStats)")).fetchall()
        }
        stock_columns = {row[1] for row in await (await connection.execute("PRAGMA table_info(Stocks)")).fetchall()}
        legacy = await (
            await connection.execute(
                "SELECT BetAmount, WinAmount, LossAmount, Rounds FROM GamblingStats WHERE Feature = 'legacy'"
            )
        ).fetchone()
        stock = await (
            await connection.execute(
                "SELECT CurrentPrice, TotalShares, SmoothedUsage, PeriodUsage FROM Stocks WHERE Symbol = 'OLD'"
            )
        ).fetchone()
    assert {"Rounds", "StakedSinceEpoch", "PaidOut", "RakebackPaid", "EpochStart"} <= gambling_columns
    assert "PeriodUsage" in stock_columns
    assert legacy == (10, 20, 30, 0)
    assert stock == (10, 5, 7.5, 11)


@pytest.mark.asyncio
async def test_house_banked_pool_accrual_is_signed_atomic_and_idempotent(db: DatabaseManager) -> None:
    await _fund(db, 1)
    await db.economy.reserve_stake(key="house:loss", user_id=1, amount=100, game="slots")
    await db.economy.settle_stake(key="house:loss", payout=0, transaction_type="slots")
    after_loss = await db.economy.get_yield_pool()
    assert after_loss["balance"] == 95
    assert after_loss["lifetime_house_banked"] == 95

    duplicate = await db.economy.settle_stake(key="house:loss", payout=0, transaction_type="slots")
    assert duplicate.state == "duplicate"
    assert (await db.economy.get_yield_pool())["balance"] == 95

    await db.economy.reserve_stake(key="house:win", user_id=1, amount=100, game="slots")
    await db.economy.settle_stake(key="house:win", payout=300, transaction_type="slots")
    pool = await db.economy.get_yield_pool()
    assert pool["balance"] == -105
    assert pool["lifetime_house_banked"] == -105


@pytest.mark.asyncio
async def test_stock_trade_tax_funds_pool_without_changing_trade_amounts(db: DatabaseManager) -> None:
    await _fund(db, 10)
    async with db._get_connection() as connection:
        await connection.execute(
            """
            INSERT INTO Stocks
                (Symbol, Name, Emoji, CurrentPrice, PreviousPrice, ShareReserve)
            VALUES ('TAX', 'Tax', ':tax:', 100, 100, 100000)
            """
        )
        await connection.commit()
    assert await db.stock.execute_buy(
        user_id=10,
        symbol="TAX",
        shares=10,
        exec_price=100.0,
        tax=10,
        total_cost=1010,
        spot_after=101.0,
        reserve_after=99990.0,
    )
    assert await db.economy.get_user_currency(10) == 8990
    transaction = (await db.stock.get_transactions(10))[0]
    assert transaction["tax"] == 10
    assert transaction["total"] == 1010
    assert (await db.economy.get_yield_pool())["lifetime_trade_tax"] == 10


@pytest.mark.asyncio
async def test_duel_pool_settlement_matches_declared_example_and_is_idempotent(db: DatabaseManager) -> None:
    await _fund(db, 1, 2000)
    await _fund(db, 2, 2000)
    outcomes = await db.economy.reserve_stakes(
        stakes=(("duel:a", 1, 1000), ("duel:b", 2, 1000)),
        game="duel",
    )
    assert {outcome.state for outcome in outcomes.values()} == {"reserved"}
    result = await db.economy.settle_pool(
        settlement_id="duel:test",
        stakes={"duel:a": "winner", "duel:b": "loser"},
        winning_side="winner",
        game="duel",
    )
    assert result.payouts == {"duel:a": 1900, "duel:b": 0}
    assert result.rakeback == {"duel:a": 0, "duel:b": 50}
    assert result.pool_accrual == 50
    assert await db.economy.get_user_currency(1) == 2900
    assert await db.economy.get_user_currency(2) == 1000
    assert (await db.economy.get_yield_pool())["balance"] == 50

    retry = await db.economy.settle_pool(
        settlement_id="duel:test",
        stakes={"duel:a": "winner", "duel:b": "loser"},
        winning_side="winner",
        game="duel",
    )
    assert retry.state == "duplicate"
    assert await db.economy.get_user_currency(1) == 2900
    assert (await db.economy.get_yield_pool())["balance"] == 50


@pytest.mark.asyncio
async def test_void_pool_refunds_every_stake_without_stats_or_pool_effect(db: DatabaseManager) -> None:
    await _fund(db, 1, 1000)
    await _fund(db, 2, 1000)
    await db.economy.reserve_stakes(stakes=(("void:a", 1, 200), ("void:b", 2, 300)), game="spectator")
    result = await db.economy.settle_pool(
        settlement_id="void:test",
        stakes={"void:a": "win", "void:b": "win"},
        winning_side=None,
        game="spectator",
        void=True,
    )
    assert result.voided and result.paid_out == 500 and result.pool_accrual == 0
    assert await db.economy.get_user_currency(1) == 1000
    assert await db.economy.get_user_currency(2) == 1000
    assert await db.economy.get_global_gambling_stats() == []
    assert (await db.economy.get_yield_pool())["balance"] == 0


@pytest.mark.asyncio
async def test_pool_settlement_identifier_cannot_be_reused_for_other_stakes(db: DatabaseManager) -> None:
    for user_id in (1, 2, 3, 4):
        await _fund(db, user_id, 1000)
    await db.economy.reserve_stakes(stakes=(("first:a", 1, 100), ("first:b", 2, 100)), game="duel")
    await db.economy.settle_pool(
        settlement_id="shared-id",
        stakes={"first:a": "a", "first:b": "b"},
        winning_side="a",
        game="duel",
    )
    await db.economy.reserve_stakes(stakes=(("second:a", 3, 100), ("second:b", 4, 100)), game="duel")
    duplicate = await db.economy.settle_pool(
        settlement_id="shared-id",
        stakes={"second:a": "a", "second:b": "b"},
        winning_side="a",
        game="duel",
    )
    assert duplicate.state == "duplicate"
    assert (await db.economy.get_operation("second:a"))["State"] == "reserved"  # type: ignore[index]
    assert (await db.economy.get_operation("second:b"))["State"] == "reserved"  # type: ignore[index]
    assert await db.economy.get_user_currency(3) == 900
    assert await db.economy.get_user_currency(4) == 900


@pytest.mark.asyncio
async def test_spectator_cap_is_shared_and_breaching_stake_is_refused_whole(db: DatabaseManager) -> None:
    for user_id in (1, 2, 3):
        await _fund(db, user_id, 2000)
    market_id = await db.economy.create_spectator_market("blackjack:cap")
    first = await db.economy.place_spectator_bet(
        market_id=market_id, player_id=1, user_id=2, side="win", amount=600, market_cap=1000
    )
    assert first["state"] == "reserved"
    before = await db.economy.get_user_currency(3)
    refused = await db.economy.place_spectator_bet(
        market_id=market_id, player_id=1, user_id=3, side="lose", amount=401, market_cap=1000
    )
    assert refused == {"state": "full", "remaining": 400}
    assert await db.economy.get_user_currency(3) == before
    filled = await db.economy.place_spectator_bet(
        market_id=market_id, player_id=1, user_id=3, side="lose", amount=400, market_cap=1000
    )
    assert filled["market_total"] == 1000
    further = await db.economy.place_spectator_bet(
        market_id=market_id, player_id=1, user_id=2, side="win", amount=1, market_cap=1000
    )
    assert further["state"] == "full"


@pytest.mark.asyncio
async def test_spectator_position_can_grow_same_side_but_not_cross_sides(db: DatabaseManager) -> None:
    await _fund(db, 2, 2000)
    market_id = await db.economy.create_spectator_market("blackjack:add")
    await db.economy.place_spectator_bet(
        market_id=market_id, player_id=1, user_id=2, side="win", amount=200, market_cap=1000
    )
    added = await db.economy.place_spectator_bet(
        market_id=market_id, player_id=1, user_id=2, side="win", amount=300, market_cap=1000
    )
    crossed = await db.economy.place_spectator_bet(
        market_id=market_id, player_id=1, user_id=2, side="lose", amount=100, market_cap=1000
    )
    assert added["position"] == 500
    assert crossed["state"] == "opposite_side"
    assert await db.economy.get_user_currency(2) == 1500


@pytest.mark.asyncio
async def test_spectator_market_settles_both_sides_once_and_voids_one_sided(db: DatabaseManager) -> None:
    for user_id in (2, 3, 4):
        await _fund(db, user_id, 2000)
    market_id = await db.economy.create_spectator_market("blackjack:settle")
    await db.economy.place_spectator_bet(
        market_id=market_id, player_id=1, user_id=2, side="win", amount=400, market_cap=1000
    )
    await db.economy.place_spectator_bet(
        market_id=market_id, player_id=1, user_id=3, side="lose", amount=600, market_cap=1000
    )
    settled = await db.economy.settle_spectator_market(market_id, "win")
    assert settled is not None and not settled.voided
    assert settled.paid_out <= settled.total_staked
    balances = (await db.economy.get_user_currency(2), await db.economy.get_user_currency(3))
    pool_balance = (await db.economy.get_yield_pool())["balance"]
    retry = await db.economy.settle_spectator_market(market_id, "win")
    assert retry is not None and retry.state == "duplicate"
    assert balances == (await db.economy.get_user_currency(2), await db.economy.get_user_currency(3))
    assert (await db.economy.get_yield_pool())["balance"] == pool_balance

    one_sided = await db.economy.create_spectator_market("blackjack:void")
    await db.economy.place_spectator_bet(
        market_id=one_sided, player_id=1, user_id=4, side="win", amount=500, market_cap=1000
    )
    voided = await db.economy.settle_spectator_market(one_sided, "win")
    assert voided is not None and voided.voided
    assert await db.economy.get_user_currency(4) == 2000


@pytest.mark.asyncio
async def test_spectator_retry_after_pool_commit_preserves_original_outcome(db: DatabaseManager) -> None:
    """A crash between pool commit and market-state update must recover truthfully."""
    await _fund(db, 1)
    await _fund(db, 2)
    market_id = await db.economy.create_spectator_market("blackjack:crash-window")
    await db.economy.place_spectator_bet(
        market_id=market_id, player_id=99, user_id=1, side="win", amount=100, market_cap=200
    )
    await db.economy.place_spectator_bet(
        market_id=market_id, player_id=99, user_id=2, side="lose", amount=100, market_cap=200
    )
    positions = await db.economy.close_spectator_market(market_id)
    stakes = {str(position["stake_key"]): str(position["side"]) for position in positions}

    original = await db.economy.settle_pool(
        settlement_id=f"spectator:{market_id}",
        stakes=stakes,
        winning_side="win",
        game="spectator",
    )
    assert original.winning_side == "win"

    # Simulate restart recovery with a conflicting caller outcome. The durable
    # settlement marker, not the retry arguments, remains authoritative.
    retry = await db.economy.settle_spectator_market(market_id, "lose")
    assert retry is not None and retry.state == "duplicate"
    assert retry.winning_side == "win"
    async with db._get_connection() as connection:
        market = await (
            await connection.execute("SELECT State, Outcome FROM SpectatorMarkets WHERE Id = ?", (market_id,))
        ).fetchone()
    assert market == ("settled", "win")


@pytest.mark.asyncio
async def test_stale_sweeper_leaves_fresh_in_progress_reservation_alone(db: DatabaseManager) -> None:
    await _fund(db, 1, 1000)
    await _fund(db, 2, 1000)
    await db.economy.reserve_stake(key="old", user_id=1, amount=100, game="blackjack")
    await db.economy.reserve_stake(key="fresh", user_id=2, amount=100, game="blackjack")
    async with db._get_connection() as connection:
        await connection.execute(
            "UPDATE EconomyOperations SET CreatedAt = datetime('now', '-1 hour') WHERE OperationKey = 'old'"
        )
        await connection.commit()
    count, total = await db.economy.refund_stale_reservations(300)
    assert (count, total) == (1, 100)
    assert (await db.economy.get_operation("old"))["State"] == "settled"  # type: ignore[index]
    assert (await db.economy.get_operation("fresh"))["State"] == "reserved"  # type: ignore[index]
    assert await db.economy.get_user_currency(1) == 1000
    assert await db.economy.get_user_currency(2) == 900


@pytest.mark.asyncio
async def test_deferred_startup_snapshot_does_not_sweep_new_process_reservations(db: DatabaseManager) -> None:
    await _fund(db, 1, 1000)
    await _fund(db, 2, 1000)
    await db.economy.reserve_stake(key="startup-orphan", user_id=1, amount=100, game="blackjack")
    startup_snapshot = await db.economy.get_stale_reservations(0)

    # This reservation represents a live game created by the new process after
    # its startup snapshot was captured.
    await db.economy.reserve_stake(key="new-live-game", user_id=2, amount=100, game="blackjack")
    count, total = await db.economy.refund_reservations(startup_snapshot)

    assert (count, total) == (1, 100)
    assert (await db.economy.get_operation("startup-orphan"))["State"] == "settled"  # type: ignore[index]
    assert (await db.economy.get_operation("new-live-game"))["State"] == "reserved"  # type: ignore[index]
    assert await db.economy.get_user_currency(1) == 1000
    assert await db.economy.get_user_currency(2) == 900
    assert (await db.economy.get_yield_pool())["balance"] == 0


@pytest.mark.asyncio
async def test_time_weighted_holdings_cover_full_midpoint_and_last_hour(db: DatabaseManager) -> None:
    start = datetime(2026, 1, 1)
    end = start + timedelta(days=7)
    midpoint = start + (end - start) / 2
    for user_id, side, when in (
        (1, "buy", start),
        (2, "buy", midpoint),
        (3, "buy", start),
        (3, "sell", midpoint),
        (4, "buy", end - timedelta(hours=1)),
    ):
        await db.stock.add_transaction(
            user_id=user_id,
            symbol="TIME",
            side=side,
            shares=100,
            exec_price=1,
            tax=0,
            total_amount=0,
            date_added=when.isoformat(sep=" "),
        )
    weights = (await db.stock.get_time_weighted_holdings(start, end))["TIME"]
    assert weights[1] == pytest.approx(100)
    assert weights[2] == pytest.approx(50)
    assert weights[3] == pytest.approx(50)
    assert weights[4] / weights[1] < 0.01


@pytest.mark.asyncio
async def test_dividend_distribution_floors_carries_and_is_idempotent(db: DatabaseManager) -> None:
    start = datetime(2026, 1, 1)
    end = start + timedelta(days=7)
    async with db._get_connection() as connection:
        await connection.execute(
            "INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice, PreviousPrice, PeriodUsage) VALUES ('DIV', 'Dividend', ':d:', 1, 1, 10)"
        )
        await connection.execute("UPDATE YieldPool SET Balance = 1000 WHERE Id = 1")
        await connection.commit()
    for user_id in (1, 2, 3):
        await db.stock.add_transaction(
            user_id=user_id,
            symbol="DIV",
            side="buy",
            shares=1,
            exec_price=1,
            tax=0,
            total_amount=-1,
            date_added=start.isoformat(sep=" "),
        )
    outcome = await db.economy.distribute_dividends(
        period_start=start,
        period_end=end,
        next_distribution_at=end + timedelta(days=7),
    )
    assert outcome.distributed == 999 and outcome.recipients == 3
    assert {await db.economy.get_user_currency(user_id) for user_id in (1, 2, 3)} == {333}
    pool = await db.economy.get_yield_pool()
    assert pool["balance"] == 1
    async with db._get_connection() as connection:
        usage_row = await (await connection.execute("SELECT PeriodUsage FROM Stocks WHERE Symbol = 'DIV'")).fetchone()
        tx_row = await (
            await connection.execute("SELECT COUNT(*) FROM CurrencyTransactions WHERE Type = 'stock_dividend'")
        ).fetchone()
    assert usage_row is not None and tx_row is not None
    usage = usage_row[0]
    tx_count = tx_row[0]
    assert usage == 0 and tx_count == 3
    balances = [await db.economy.get_user_currency(user_id) for user_id in (1, 2, 3)]
    duplicate = await db.economy.distribute_dividends(
        period_start=start,
        period_end=end,
        next_distribution_at=end + timedelta(days=7),
    )
    assert duplicate.state == "duplicate"
    assert [await db.economy.get_user_currency(user_id) for user_id in (1, 2, 3)] == balances


@pytest.mark.asyncio
async def test_deficit_and_zero_usage_defer_without_resetting_accumulators(db: DatabaseManager) -> None:
    start = datetime(2026, 1, 1)
    end = start + timedelta(days=7)
    async with db._get_connection() as connection:
        await connection.execute(
            "INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice, PreviousPrice, PeriodUsage) VALUES ('DEF', 'Deficit', ':x:', 1, 1, 9)"
        )
        await connection.execute("UPDATE YieldPool SET Balance = -10 WHERE Id = 1")
        await connection.commit()
    outcome = await db.economy.distribute_dividends(
        period_start=start,
        period_end=end,
        next_distribution_at=end + timedelta(days=7),
    )
    assert outcome.state == "deferred"
    assert (await db.economy.get_yield_pool())["balance"] == -10
    async with db._get_connection() as connection:
        usage_row = await (await connection.execute("SELECT PeriodUsage FROM Stocks WHERE Symbol = 'DEF'")).fetchone()
    assert usage_row is not None
    usage = usage_row[0]
    assert usage == 9

    async with db._get_connection() as connection:
        await connection.execute("UPDATE YieldPool SET Balance = 500 WHERE Id = 1")
        await connection.execute("UPDATE Stocks SET PeriodUsage = 0")
        await connection.commit()
    no_usage = await db.economy.distribute_dividends(
        period_start=start,
        period_end=end + timedelta(days=7),
        next_distribution_at=end + timedelta(days=14),
    )
    assert no_usage.state == "deferred"
    assert (await db.economy.get_yield_pool())["balance"] == 500


@pytest.mark.asyncio
async def test_distribution_schedule_waits_remainder_then_runs_due(db: DatabaseManager) -> None:
    config = MagicMock()
    config.dividend_period_hours = AsyncMock(return_value=168)
    system = YieldSystem(db, config)
    now = datetime(2026, 1, 1)
    delay, first = await system.run_scheduled_distribution(now)
    assert first is None and delay == pytest.approx(7 * 24 * 3600)
    delay, early = await system.run_scheduled_distribution(now + timedelta(days=1))
    assert early is None and delay == pytest.approx(6 * 24 * 3600)
    delay, due = await system.run_scheduled_distribution(now + timedelta(days=7))
    assert due is not None and due.state == "deferred"
    assert delay == pytest.approx(7 * 24 * 3600)
    assert await db.economy.get_dividend_accumulation_start(now + timedelta(days=1)) == now
    delay, second_deferral = await system.run_scheduled_distribution(now + timedelta(days=14))
    assert second_deferral is not None and second_deferral.state == "deferred"
    assert await db.economy.get_dividend_accumulation_start(now + timedelta(days=2)) == now


@pytest.mark.asyncio
async def test_distribution_period_falls_back_safely_for_malformed_config(db: DatabaseManager) -> None:
    config = MagicMock()
    config.dividend_period_hours = AsyncMock(return_value=None)
    assert await YieldSystem(db, config).period_seconds() == 168 * 3600


def test_pooled_rake_identity_and_rakeback_regression_guard() -> None:
    for total in (4_000, 40_000, 400_000):
        for losing_percent in range(1, 100):
            losing = total * losing_percent // 100
            rake = pooled_rake(total, losing)
            rakeback = int(losing * RAKEBACK_RATE)
            returned = total - rake + rakeback
            assert returned == int(Decimal(str(RTP_TARGET)) * total)
            wrong_returned = total - int(total * (1 - RTP_TARGET)) + rakeback
            assert wrong_returned > RTP_TARGET * total


def test_duel_rtp_with_triple_draw_refund_is_in_tolerance() -> None:
    rtp = (26 / 27) * RTP_TARGET + (1 / 27)
    assert abs(rtp - RTP_TARGET) <= 0.005
    assert rtp <= RTP_TARGET + 0.005


def test_one_x_spectator_cap_keeps_collusion_joint_profit_negative() -> None:
    stake = 1_000
    market_cap = stake
    for win_percent in range(50, 96):
        honest_expected_value = 2 * (win_percent / 100) * stake
        joint_profit = 0.925 * market_cap - honest_expected_value
        assert joint_profit < 0


@pytest.mark.asyncio
async def test_period_usage_persists_without_changing_smoothed_usage(db: DatabaseManager) -> None:
    async with db._get_connection() as connection:
        await connection.execute(
            "INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice, PreviousPrice, SmoothedUsage) VALUES ('USE', 'Usage', ':u:', 10, 9, 7.5)"
        )
        await connection.commit()
    await db.stock.bulk_update_prices([("USE", 11.0, 10.0, 8.25, 13)], completed_at=123)
    stock = await db.stock.get_stock("USE")
    assert stock is not None
    assert stock["smoothed_usage"] == 8.25
    assert stock["period_usage"] == 13


@pytest.mark.asyncio
async def test_realized_rtp_counters_match_independent_session_total(db: DatabaseManager) -> None:
    await _fund(db, 1, 10_000)
    payouts = (0, 50, 100, 200)
    for index, payout in enumerate(payouts):
        key = f"session:{index}"
        await db.economy.reserve_stake(key=key, user_id=1, amount=100, game="session")
        await db.economy.settle_stake(key=key, payout=payout, transaction_type="session")
    row = (await db.economy.get_global_gambling_stats())[0]
    _feature, bet, _win, _loss, rounds, staked, paid, rakeback, epoch = row
    expected_rakeback = sum(int(max(0, 100 - payout) * RAKEBACK_RATE) for payout in payouts)
    assert (bet, rounds, staked, paid, rakeback) == (400, 4, 400, sum(payouts), expected_rakeback)
    assert (paid + rakeback) / staked == (sum(payouts) + expected_rakeback) / 400
    assert epoch is not None


@pytest.mark.asyncio
async def test_pool_reconciles_across_losses_wins_pushes_pooled_play_and_tax(db: DatabaseManager) -> None:
    await _fund(db, 1, 20_000)
    await _fund(db, 2, 2_000)
    for name, payout in (("loss", 0), ("push", 100), ("win", 200)):
        key = f"mixed:{name}"
        await db.economy.reserve_stake(key=key, user_id=1, amount=100, game="mixed")
        await db.economy.settle_stake(key=key, payout=payout, transaction_type="mixed")
    await db.economy.reserve_stakes(
        stakes=(("mixed:duel:a", 1, 1000), ("mixed:duel:b", 2, 1000)),
        game="duel",
    )
    await db.economy.settle_pool(
        settlement_id="mixed:duel",
        stakes={"mixed:duel:a": "a", "mixed:duel:b": "b"},
        winning_side="a",
        game="duel",
    )
    async with db._get_connection() as connection:
        await connection.execute(
            "INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice, PreviousPrice) VALUES ('MIX', 'Mixed', ':m:', 1, 1)"
        )
        await connection.commit()
    await db.stock.execute_buy(
        user_id=1,
        symbol="MIX",
        shares=1,
        exec_price=1,
        tax=10,
        total_cost=11,
        spot_after=1,
        reserve_after=99_999,
    )
    pool = await db.economy.get_yield_pool()
    # House: +95 loss, +0 push, -100 win. Pooled duel: +50. Trade tax: +10.
    assert pool["lifetime_house_banked"] == -5
    assert pool["lifetime_pooled"] == 50
    assert pool["lifetime_trade_tax"] == 10
    assert pool["balance"] == 55


@pytest.mark.asyncio
async def test_parimutuel_odds_improve_with_opposition_and_rounding_stays_in_pool(db: DatabaseManager) -> None:
    for user_id in (1, 2, 3):
        await _fund(db, user_id, 1000)
    await db.economy.reserve_stakes(
        stakes=(("odds:w1", 1, 25), ("odds:w2", 2, 25), ("odds:l", 3, 50)),
        game="spectator",
    )
    result = await db.economy.settle_pool(
        settlement_id="odds:rounding",
        stakes={"odds:w1": "win", "odds:w2": "win", "odds:l": "lose"},
        winning_side="win",
        game="spectator",
    )
    assert result.payouts["odds:w1"] == result.payouts["odds:w2"] == 47
    assert result.paid_out <= result.total_staked
    assert result.pool_accrual == 4  # includes the one-unit winner split remainder

    balanced_return_per_unit = (200 - pooled_rake(200, 100)) / 100
    lopsided_return_per_unit = (1000 - pooled_rake(1000, 900)) / 100
    assert lopsided_return_per_unit > balanced_return_per_unit


@pytest.mark.asyncio
async def test_concurrent_distribution_runs_credit_once(db: DatabaseManager) -> None:
    start = datetime(2026, 1, 1)
    end = start + timedelta(days=7)
    async with db._get_connection() as connection:
        await connection.execute(
            "INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice, PreviousPrice, PeriodUsage) VALUES ('CON', 'Concurrent', ':c:', 1, 1, 1)"
        )
        await connection.execute("UPDATE YieldPool SET Balance = 100 WHERE Id = 1")
        await connection.commit()
    await db.stock.add_transaction(
        user_id=9,
        symbol="CON",
        side="buy",
        shares=1,
        exec_price=1,
        tax=0,
        total_amount=-1,
        date_added=start.isoformat(sep=" "),
    )
    results = await asyncio.gather(
        db.economy.distribute_dividends(
            period_start=start, period_end=end, next_distribution_at=end + timedelta(days=7)
        ),
        db.economy.distribute_dividends(
            period_start=start, period_end=end, next_distribution_at=end + timedelta(days=7)
        ),
    )
    assert {result.state for result in results} == {"settled", "duplicate"}
    assert await db.economy.get_user_currency(9) == 100


@pytest.mark.asyncio
async def test_owner_dashboard_is_aggregate_only_and_handles_cold_data() -> None:
    command = AdminCommands.yield_stats_dashboard
    assert command.requires.privilege_level is PrivilegeLevel.BOT_OWNER

    economy_system = SimpleNamespace(get_gambling_stats=AsyncMock(return_value=[]))
    economy_repo = SimpleNamespace(
        get_yield_pool=AsyncMock(
            return_value={
                "balance": 0,
                "lifetime_house_banked": 0,
                "lifetime_pooled": 0,
                "lifetime_trade_tax": 0,
                "next_distribution_at": None,
            }
        ),
        get_recent_dividend_runs=AsyncMock(return_value=[]),
    )
    handler = SimpleNamespace(
        economy_system=economy_system,
        db=SimpleNamespace(economy=economy_repo),
        config=SimpleNamespace(currency_symbol=AsyncMock(return_value="$")),
    )
    ctx = SimpleNamespace(send=AsyncMock())
    callback = cast(Any, command.callback)
    await callback(handler, ctx)
    output = ctx.send.await_args.args[0]
    assert "No post-upgrade gambling data" in output
    assert "No distributions" in output
    assert "UserId" not in output and "display name" not in output

    economy_system.get_gambling_stats.return_value = [("legacy", 10, 5, 5, 0, 0, 0, 0, None)]
    ctx.send.reset_mock()
    await callback(handler, ctx)
    empty_epoch_output = ctx.send.await_args.args[0]
    assert "RTP unavailable" in empty_epoch_output
    assert "0 rounds" in empty_epoch_output


@pytest.mark.asyncio
async def test_distribution_failure_rolls_back_every_credit_and_ledger_row(db: DatabaseManager) -> None:
    start = datetime(2026, 1, 1)
    end = start + timedelta(days=7)
    async with db._get_connection() as connection:
        await connection.execute(
            "INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice, PreviousPrice, PeriodUsage) VALUES ('FAIL', 'Failure', ':f:', 1, 1, 1)"
        )
        await connection.execute("UPDATE YieldPool SET Balance = 100 WHERE Id = 1")
        await connection.execute(
            """
            CREATE TRIGGER fail_second_dividend BEFORE INSERT ON DividendPayouts
            WHEN NEW.UserId = 2 BEGIN SELECT RAISE(ABORT, 'injected failure'); END
            """
        )
        await connection.commit()
    for user_id in (1, 2):
        await db.stock.add_transaction(
            user_id=user_id,
            symbol="FAIL",
            side="buy",
            shares=1,
            exec_price=1,
            tax=0,
            total_amount=-1,
            date_added=start.isoformat(sep=" "),
        )
    with pytest.raises(Exception, match="injected failure"):
        await db.economy.distribute_dividends(
            period_start=start,
            period_end=end,
            next_distribution_at=end + timedelta(days=7),
        )
    assert await db.economy.get_user_currency(1) == 0
    assert await db.economy.get_user_currency(2) == 0
    assert (await db.economy.get_yield_pool())["balance"] == 100
    async with db._get_connection() as connection:
        run_row = await (await connection.execute("SELECT COUNT(*) FROM DividendRuns")).fetchone()
        payout_row = await (await connection.execute("SELECT COUNT(*) FROM DividendPayouts")).fetchone()
        usage_row = await (await connection.execute("SELECT PeriodUsage FROM Stocks WHERE Symbol = 'FAIL'")).fetchone()
    assert run_row is not None and payout_row is not None and usage_row is not None
    run_count = run_row[0]
    payout_count = payout_row[0]
    usage = usage_row[0]
    assert (run_count, payout_count, usage) == (0, 0, 1)
