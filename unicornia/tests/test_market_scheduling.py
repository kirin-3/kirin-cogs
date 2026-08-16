"""Restart-safe stock-market scheduling tests."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.systems.market_system import MARKET_TICK_INTERVAL, MarketSystem


@pytest_asyncio.fixture
async def market(tmp_path: Path) -> AsyncGenerator[MarketSystem, None]:
    db = DatabaseManager(str(tmp_path / "market.db"))
    await db.connect()
    await db.initialize()
    await db.stock.create_stock("ABC", "Example", "📈", 100)
    config = MagicMock()
    config.currency_symbol = AsyncMock(return_value="$")
    system = MarketSystem(db, config, MagicMock(guilds=[]), MagicMock())
    await system.initialize()
    system.update_dashboard = AsyncMock()
    yield system
    await db.close()


@pytest.mark.asyncio
async def test_first_run_initializes_without_tick(market: MarketSystem) -> None:
    market.market_tick = AsyncMock(wraps=market.market_tick)  # type: ignore[method-assign]

    delay = await market.run_scheduled_tick(now=1_000)

    assert delay == MARKET_TICK_INTERVAL
    market.market_tick.assert_not_awaited()  # type: ignore[attr-defined]
    assert await market.get_last_market_tick() == 1_000


@pytest.mark.asyncio
async def test_frequent_restarts_do_not_reset_schedule(market: MarketSystem) -> None:
    await market.set_last_market_tick(1_000)
    market.market_tick = AsyncMock(wraps=market.market_tick)  # type: ignore[method-assign]

    assert await market.run_scheduled_tick(now=4_599) == 1
    with patch("unicornia.systems.market_system.time.time", return_value=4_600):
        assert await market.run_scheduled_tick(now=4_600) == MARKET_TICK_INTERVAL

    market.market_tick.assert_awaited_once()  # type: ignore[attr-defined]
    assert await market.get_last_market_tick() == 4_600


@pytest.mark.asyncio
async def test_long_outage_runs_exactly_one_catchup(market: MarketSystem) -> None:
    await market.set_last_market_tick(1_000)
    market.market_tick = AsyncMock(wraps=market.market_tick)  # type: ignore[method-assign]

    with patch("unicornia.systems.market_system.time.time", return_value=50_000):
        await market.run_scheduled_tick(now=50_000)

    market.market_tick.assert_awaited_once()  # type: ignore[attr-defined]
    assert await market.get_last_market_tick() == 50_000


@pytest.mark.asyncio
async def test_recent_tick_runs_none(market: MarketSystem) -> None:
    await market.set_last_market_tick(10_000)
    market.market_tick = AsyncMock(wraps=market.market_tick)  # type: ignore[method-assign]

    assert await market.run_scheduled_tick(now=10_100) == MARKET_TICK_INTERVAL - 100
    market.market_tick.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_failed_tick_does_not_advance_timestamp(market: MarketSystem) -> None:
    await market.set_last_market_tick(1_000)
    market.emoji_buffer["ABC"] = 25
    cache_before = dict(market.stocks_cache["ABC"])
    market.db.stock.bulk_update_prices = AsyncMock(side_effect=RuntimeError("database unavailable"))  # type: ignore[method-assign]

    with (
        patch("unicornia.systems.market_system.random.random", return_value=1.0),
        patch("unicornia.systems.market_system.random.gauss", return_value=0.0),
        patch("unicornia.systems.market_system.time.time", return_value=4_600),
    ):
        with pytest.raises(RuntimeError, match="database unavailable"):
            await market.run_scheduled_tick(now=4_600)

    assert await market.get_last_market_tick() == 1_000
    assert market.stocks_cache["ABC"] == cache_before
    assert market.emoji_buffer["ABC"] == 25


@pytest.mark.asyncio
async def test_timestamp_failure_rolls_back_price_and_ema(market: MarketSystem) -> None:
    await market.set_last_market_tick(1_000)
    market.emoji_buffer["ABC"] = 25
    cache_before = dict(market.stocks_cache["ABC"])
    stock_before = await market.db.stock.get_stock("ABC")
    async with market.db._get_connection() as connection:
        await connection.execute(
            """
            CREATE TRIGGER reject_market_tick_timestamp
            BEFORE UPDATE OF Value ON BotConfig
            WHEN OLD.Key = 'LastMarketTick'
            BEGIN
                SELECT RAISE(ABORT, 'timestamp write failed');
            END
            """
        )
        await connection.commit()

    with (
        patch("unicornia.systems.market_system.random.random", return_value=1.0),
        patch("unicornia.systems.market_system.random.gauss", return_value=0.0),
        patch("unicornia.systems.market_system.time.time", return_value=4_600),
    ):
        with pytest.raises(sqlite3.IntegrityError, match="timestamp write failed"):
            await market.run_scheduled_tick(now=4_600)

    assert await market.db.stock.get_stock("ABC") == stock_before
    assert await market.get_last_market_tick() == 1_000
    assert market.stocks_cache["ABC"] == cache_before
    assert market.emoji_buffer["ABC"] == 25


@pytest.mark.asyncio
async def test_dashboard_failure_does_not_replay_committed_tick(market: MarketSystem) -> None:
    await market.set_last_market_tick(1_000)
    market.emoji_buffer["ABC"] = 25
    market.update_dashboard = AsyncMock(side_effect=RuntimeError("discord unavailable"))

    with (
        patch("unicornia.systems.market_system.random.random", return_value=1.0),
        patch("unicornia.systems.market_system.random.gauss", return_value=0.0),
        patch("unicornia.systems.market_system.time.time", return_value=4_600),
    ):
        with pytest.raises(RuntimeError, match="discord unavailable"):
            await market.run_scheduled_tick(now=4_600)

    committed = await market.db.stock.get_stock("ABC")
    assert committed is not None
    assert await market.get_last_market_tick() == 4_600
    assert market.emoji_buffer["ABC"] == 0

    market.update_dashboard = AsyncMock()
    delay = await market.run_scheduled_tick(now=4_660)
    after_retry = await market.db.stock.get_stock("ABC")
    assert delay == MARKET_TICK_INTERVAL - 60
    assert after_retry == committed
    market.update_dashboard.assert_not_awaited()  # type: ignore[attr-defined]
