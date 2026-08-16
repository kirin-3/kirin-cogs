"""Bonding-curve and reserve-aware trade integration tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.stock_market import (
    INITIAL_SHARE_RESERVE,
    P_MIN,
    TRADE_IMPACT_LIMIT,
    buy_quote,
    maximum_trade_size,
    sell_quote,
)
from unicornia.systems.market_system import MarketSystem

USER = 9911


@pytest_asyncio.fixture
async def market(tmp_path: Path) -> AsyncGenerator[MarketSystem, None]:
    db = DatabaseManager(str(tmp_path / "trades.db"))
    await db.connect()
    await db.initialize()
    await db.stock.create_stock("ABC", "Example", "📈", 100)
    await db.economy.add_currency(USER, 100_000_000, "test", "test")
    config = MagicMock()
    config.currency_symbol = AsyncMock(return_value="$")
    system = MarketSystem(db, config, MagicMock(guilds=[]), MagicMock())
    await system.initialize()
    system.update_dashboard = AsyncMock()
    yield system
    await db.close()


def test_buying_ten_percent_moves_spot_about_eleven_percent() -> None:
    quote = buy_quote(100.0, 100_000.0, 10_000)
    assert quote.spot_after == pytest.approx(111.1111111111)


def test_buy_cost_is_convex_and_sell_proceeds_are_concave() -> None:
    buy_small = buy_quote(100.0, 100_000.0, 5_000).average_execution_price * 5_000
    buy_large = buy_quote(100.0, 100_000.0, 10_000).average_execution_price * 10_000
    sell_small = sell_quote(100.0, 100_000.0, 5_000).average_execution_price * 5_000
    sell_large = sell_quote(100.0, 100_000.0, 10_000).average_execution_price * 10_000
    assert buy_large > 2 * buy_small
    assert buy_large / buy_small == pytest.approx(2.054079, rel=1e-5)
    assert sell_large < 2 * sell_small
    assert sell_large / sell_small == pytest.approx(1.953471, rel=1e-5)


def test_marginal_rate_worsens_within_each_trade() -> None:
    assert buy_quote(100, 100_000, 1).spot_after < buy_quote(100, 100_000, 10_000).spot_after
    assert sell_quote(100, 100_000, 1).spot_after > sell_quote(100, 100_000, 10_000).spot_after


@pytest.mark.parametrize("reserve", [50_000.0, 100_000.0, 250_000.0])
def test_caps_are_inverse_symmetric_and_max_buy_is_reversible(reserve: float) -> None:
    buy_amount = maximum_trade_size(reserve, "buy")
    bought = buy_quote(100.0, reserve, buy_amount)
    assert maximum_trade_size(bought.reserve_after, "sell") >= buy_amount
    sold = sell_quote(bought.spot_after, bought.reserve_after, buy_amount)
    assert sold.spot_after == pytest.approx(100.0)
    assert sold.reserve_after == pytest.approx(reserve)
    assert bought.spot_after / 100.0 == pytest.approx(1.0 / (1.0 - TRADE_IMPACT_LIMIT))
    max_sell = maximum_trade_size(reserve, "sell")
    sold_at_cap = sell_quote(100.0, reserve, max_sell)
    assert sold_at_cap.spot_after / 100.0 == pytest.approx(1.0 - TRADE_IMPACT_LIMIT, rel=2e-5)
    assert sold_at_cap.spot_after > P_MIN


def test_splitting_a_buy_has_no_curve_cost_advantage() -> None:
    whole = buy_quote(100.0, 100_000.0, 10_000)
    first = buy_quote(100.0, 100_000.0, 5_000)
    second = buy_quote(first.spot_after, first.reserve_after, 5_000)
    split_cost = first.average_execution_price * 5_000 + second.average_execution_price * 5_000
    assert split_cost == pytest.approx(whole.average_execution_price * 10_000)
    assert second.spot_after / first.spot_after > first.spot_after / 100.0


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_every_permitted_trade_stays_inside_impact_band(side: str) -> None:
    reserve = 100_000.0
    maximum = maximum_trade_size(reserve, side)
    for amount in (1, maximum // 2, maximum):
        quote = buy_quote(100.0, reserve, amount) if side == "buy" else sell_quote(100.0, reserve, amount)
        factor = quote.spot_after / 100.0
        assert 1.0 - TRADE_IMPACT_LIMIT - 1e-9 <= factor <= 1.0 / (1.0 - TRADE_IMPACT_LIMIT) + 1e-9


@pytest.mark.asyncio
async def test_round_trip_restores_price_reserve_and_loses_only_tax(market: MarketSystem) -> None:
    user = SimpleNamespace(id=USER)
    starting_balance = await market.db.economy.get_user_currency(USER)
    bought, _ = await market.buy_stock(user, "ABC", 10_000)  # type: ignore[arg-type]
    sold, _ = await market.sell_stock(user, "ABC", 10_000)  # type: ignore[arg-type]
    ending_balance = await market.db.economy.get_user_currency(USER)
    stock = await market.db.stock.get_stock("ABC")
    rows = list(reversed(await market.db.stock.get_transactions(USER)))
    assert bought and sold and stock is not None
    assert stock["price"] == pytest.approx(100.0)
    assert stock["share_reserve"] == pytest.approx(INITIAL_SHARE_RESERVE)
    assert starting_balance - ending_balance == rows[0]["tax"] + rows[1]["tax"]
    assert ending_balance <= starting_balance


@pytest.mark.asyncio
async def test_sell_then_buy_round_trip_is_not_profitable(market: MarketSystem) -> None:
    user = SimpleNamespace(id=USER)
    seeded, _ = await market.buy_stock(user, "ABC", 5_000)  # type: ignore[arg-type]
    starting_balance = await market.db.economy.get_user_currency(USER)
    starting_price = market.stocks_cache["ABC"]["price"]
    starting_reserve = market.stocks_cache["ABC"]["share_reserve"]

    sold, _ = await market.sell_stock(user, "ABC", 5_000)  # type: ignore[arg-type]
    bought, _ = await market.buy_stock(user, "ABC", 5_000)  # type: ignore[arg-type]

    assert seeded and sold and bought
    assert await market.db.economy.get_user_currency(USER) <= starting_balance
    assert market.stocks_cache["ABC"]["price"] == pytest.approx(starting_price)
    assert market.stocks_cache["ABC"]["share_reserve"] == pytest.approx(starting_reserve)


@pytest.mark.asyncio
async def test_oversized_trade_changes_nothing(market: MarketSystem) -> None:
    before_stock = (await market.db.stock.get_stock("ABC")).copy()  # type: ignore[union-attr]
    before_balance = await market.db.economy.get_user_currency(USER)
    success, message = await market.buy_stock(
        cast(Any, SimpleNamespace(id=USER)),
        "ABC",
        maximum_trade_size(INITIAL_SHARE_RESERVE, "buy") + 1,
    )
    after_stock = await market.db.stock.get_stock("ABC")
    assert not success and "Maximum buy" in message
    assert after_stock == before_stock
    assert await market.db.economy.get_user_currency(USER) == before_balance


@pytest.mark.asyncio
async def test_first_and_successive_trades_use_mutable_configured_reserve(market: MarketSystem) -> None:
    assert market.stocks_cache["ABC"]["share_reserve"] == INITIAL_SHARE_RESERVE
    first_start = market.stocks_cache["ABC"]["price"]
    first, _ = await market.buy_stock(SimpleNamespace(id=USER), "ABC", 5_000)  # type: ignore[arg-type]
    first_end = market.stocks_cache["ABC"]["price"]
    second, _ = await market.buy_stock(SimpleNamespace(id=USER), "ABC", 5_000)  # type: ignore[arg-type]
    second_end = market.stocks_cache["ABC"]["price"]
    assert first and second
    assert first_end / first_start < second_end / first_end
