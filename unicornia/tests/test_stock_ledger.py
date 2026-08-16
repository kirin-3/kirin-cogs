"""Structured stock-ledger and legacy-import coverage."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.systems.market_system import MarketSystem

USER = 3003


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "stocks.db"))
    await manager.connect()
    await manager.initialize()
    yield manager
    await manager.close()


async def _market(db: DatabaseManager) -> MarketSystem:
    config = MagicMock()
    config.currency_symbol = AsyncMock(return_value="$")
    market = MarketSystem(db, config, MagicMock(guilds=[]), MagicMock())
    await market.initialize()
    return market


@pytest.mark.asyncio
async def test_buy_and_sell_write_exact_rows(db: DatabaseManager) -> None:
    await db.stock.create_stock("ABC", "Example", "📈", 100)
    await db.economy.add_currency(USER, 10_000, "test", "test")
    market = await _market(db)
    user = SimpleNamespace(id=USER)

    bought, _ = await market.buy_stock(user, "ABC", 10)  # type: ignore[arg-type]
    sold, _ = await market.sell_stock(user, "ABC", 4)  # type: ignore[arg-type]

    assert bought and sold
    rows = list(reversed(await db.stock.get_transactions(USER)))
    assert [(row["side"] if "side" in row else row["action"].lower(), row["shares"]) for row in rows] == [
        ("bought", 10),
        ("sold", 4),
    ]
    assert rows[0]["price"] > 0 and rows[0]["tax"] >= 0 and rows[0]["total"] > 0
    assert rows[1]["price"] > 0 and rows[1]["tax"] >= 0 and rows[1]["total"] > 0


@pytest.mark.asyncio
async def test_failed_trade_writes_no_row(db: DatabaseManager) -> None:
    await db.stock.create_stock("ABC", "Example", "📈", 100)
    market = await _market(db)

    success, _ = await market.buy_stock(SimpleNamespace(id=USER), "ABC", 10)  # type: ignore[arg-type]

    assert not success
    assert await db.stock.get_transactions(USER) == []


@pytest.mark.asyncio
async def test_symbol_containing_at_round_trips(db: DatabaseManager) -> None:
    await db.stock.create_stock("A@B", "Odd Symbol", "🧪", 50)
    await db.economy.add_currency(USER, 10_000, "test", "test")
    market = await _market(db)

    success, _ = await market.buy_stock(SimpleNamespace(id=USER), "A@B", 2)  # type: ignore[arg-type]
    _holdings, history = await market.get_portfolio_data(USER)

    assert success
    assert history["A@B"][0]["symbol"] == "A@B"


@pytest.mark.asyncio
async def test_backfill_is_flagged_and_not_repeated(db: DatabaseManager) -> None:
    async with db._get_connection() as connection:
        await connection.execute("UPDATE BotConfig SET Value = '0' WHERE Key = 'StockLedgerBackfilled'")
        await connection.execute(
            """
            INSERT INTO CurrencyTransactions (UserId, Type, Amount, Reason, DateAdded)
            VALUES (?, 'stock_buy', -505, 'Bought 5 OLD @ 100 (Tax: 5)', datetime('now'))
            """,
            (USER,),
        )
        await connection.execute(
            """
            INSERT INTO CurrencyTransactions (UserId, Type, Amount, Reason, DateAdded)
            VALUES (?, 'stock_sell', 1, 'unparseable', datetime('now'))
            """,
            (USER,),
        )
        await connection.commit()

    first = await db.stock.backfill_legacy_transactions()
    second = await db.stock.backfill_legacy_transactions()

    assert first == (1, 1)
    assert second == (0, 0)
    history = await db.stock.get_transactions(USER)
    assert len(history) == 1
    assert history[0]["symbol"] == "OLD"
    assert history[0]["imported"] is True
