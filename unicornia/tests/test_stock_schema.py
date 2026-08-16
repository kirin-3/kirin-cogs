"""Additive stock-schema and continuous-price regression coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from unicornia.database import DatabaseManager


@pytest.mark.asyncio
async def test_existing_stock_tables_receive_additive_columns(tmp_path: Path) -> None:
    manager = DatabaseManager(str(tmp_path / "legacy.db"))
    await manager.connect()
    async with manager._get_connection() as db:
        await db.execute(
            """
            CREATE TABLE Stocks (
                Symbol TEXT PRIMARY KEY, Name TEXT, Emoji TEXT, CurrentPrice INTEGER,
                PreviousPrice INTEGER, TotalShares INTEGER DEFAULT 0,
                Volatility REAL DEFAULT 1.0, Hidden INTEGER DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE StockTransactions (
                Id INTEGER PRIMARY KEY AUTOINCREMENT, UserId INTEGER NOT NULL,
                Symbol TEXT NOT NULL, Side TEXT NOT NULL CHECK (Side IN ('buy', 'sell')),
                Shares INTEGER NOT NULL, ExecPrice REAL NOT NULL, Tax INTEGER NOT NULL,
                TotalAmount INTEGER NOT NULL, IsImported INTEGER NOT NULL DEFAULT 0,
                DateAdded TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.commit()

    await manager.initialize()
    async with manager._get_connection() as db:
        stock_columns = {row[1] for row in await (await db.execute("PRAGMA table_info(Stocks)")).fetchall()}
        ledger_columns = {row[1] for row in await (await db.execute("PRAGMA table_info(StockTransactions)")).fetchall()}
    assert {"ShareReserve", "SmoothedUsage"} <= stock_columns
    assert "Kind" in ledger_columns

    await manager.stock.create_stock("OLD", "Legacy", "📜", 100)
    stock = await manager.stock.get_stock("OLD")
    assert stock is not None
    assert stock["share_reserve"] == 100_000
    assert stock["smoothed_usage"] == 0

    await manager.stock.add_transaction(
        user_id=1,
        symbol="OLD",
        side="sell",
        kind="unwind",
        shares=1,
        exec_price=50.0,
        tax=0,
        total_amount=50,
    )
    async with manager._get_connection() as db:
        row = await (await db.execute("SELECT Side, Kind FROM StockTransactions WHERE Symbol = 'OLD'")).fetchone()
    assert row == ("sell", "unwind")
    await manager.close()


@pytest.mark.asyncio
async def test_fractional_price_round_trips_through_integer_affinity(tmp_path: Path) -> None:
    manager = DatabaseManager(str(tmp_path / "fractional.db"))
    await manager.connect()
    await manager.initialize()
    await manager.stock.create_stock("REAL", "Fractional", "📐", 100)

    await manager.stock.update_stock_price("REAL", 1234.5678)
    stock = await manager.stock.get_stock("REAL")
    async with manager._get_connection() as db:
        storage = await (
            await db.execute("SELECT CurrentPrice, typeof(CurrentPrice) FROM Stocks WHERE Symbol = 'REAL'")
        ).fetchone()

    assert stock is not None
    assert stock["price"] == pytest.approx(1234.5678)
    assert storage == (1234.5678, "real")
    await manager.close()
