"""The hourly integrity check must not hold the shared connection that economy commands use."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    # A space in the path checks that the read-only connection's URI is encoded
    manager = DatabaseManager(str(tmp_path / "bot data" / "unicornia.db"))
    await manager.connect()
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_healthy_database_passes_the_quick_check(db: DatabaseManager) -> None:
    await db.economy.add_currency(1, 100, "test")

    assert await db._quick_check() == "ok"
    assert await db.check_wal_integrity() is True


@pytest.mark.asyncio
async def test_economy_keeps_working_while_the_check_runs(db: DatabaseManager) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_check() -> str:
        entered.set()
        await release.wait()
        return "ok"

    async with asyncio.timeout(5):
        with patch.object(db, "_quick_check", side_effect=slow_check):
            maintenance = asyncio.create_task(db.check_wal_integrity())
            await entered.wait()
            assert not db._lock.locked()
            await db.economy.add_currency(1, 100, "test")
            assert await db.economy.get_user_currency(1) == 100
            release.set()
            assert await maintenance is True


@pytest.mark.asyncio
async def test_failed_check_is_reported(db: DatabaseManager, caplog: pytest.LogCaptureFixture) -> None:
    with patch.object(db, "_quick_check", return_value="*** in database main ***\nPage 5: btreeInitPage() error"):
        assert await db.check_wal_integrity() is False
    assert "Database integrity check failed" in caplog.text


@pytest.mark.asyncio
async def test_a_failed_operation_does_not_leave_the_shared_transaction_open(db: DatabaseManager) -> None:
    with pytest.raises(RuntimeError):
        async with db._get_connection() as conn:
            await conn.execute("INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (1, 500)")
            raise RuntimeError("commit failed")

    assert db._conn is not None and not db._conn.in_transaction
    assert await db.economy.get_user_currency(1) == 0
    await db.economy.add_currency(1, 100, "test")
    assert await db.economy.get_user_currency(1) == 100
