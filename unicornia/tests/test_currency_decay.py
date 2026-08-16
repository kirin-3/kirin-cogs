"""Independent wallet and bank decay-policy tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.systems.currency_systems import CurrencyDecay

USER = 4004


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "decay.db"))
    await manager.connect()
    await manager.initialize()
    yield manager
    await manager.close()


def _decay(db: DatabaseManager, *, wallet_rate: float, bank_rate: float) -> CurrencyDecay:
    config = MagicMock()
    config.decay_percent = AsyncMock(return_value=wallet_rate)
    config.bank_decay_percent = AsyncMock(return_value=bank_rate)
    config.decay_max_amount = AsyncMock(return_value=0)
    config.decay_min_threshold = AsyncMock(return_value=0)
    return CurrencyDecay(db, config, MagicMock(user=SimpleNamespace(id=999)))


async def _set_equal_balances(db: DatabaseManager, amount: int = 100_000) -> None:
    await db.economy.add_currency(USER, amount, "test", "test")
    await db.economy.update_bank_balance(USER, amount)


@pytest.mark.asyncio
async def test_bank_decays_less_and_logs_separately(db: DatabaseManager) -> None:
    await _set_equal_balances(db)

    await _decay(db, wallet_rate=0.01, bank_rate=0.001)._process_decay(1_000)

    assert await db.economy.get_user_currency(USER) == 99_000
    assert await db.economy.get_bank_user(USER) == (99_900,)
    async with db._get_connection() as connection:
        rows = await (
            await connection.execute(
                "SELECT Amount, Reason FROM CurrencyTransactions WHERE UserId = ? AND Type = 'decay' ORDER BY Id",
                (USER,),
            )
        ).fetchall()
    assert rows == [(-1_000, "Wallet decay: 1.0%"), (-100, "Bank decay: 0.1%")]


@pytest.mark.asyncio
async def test_zero_bank_rate_leaves_bank_untouched(db: DatabaseManager) -> None:
    await _set_equal_balances(db)

    await _decay(db, wallet_rate=0.01, bank_rate=0.0)._process_decay(2_000)

    assert await db.economy.get_user_currency(USER) == 99_000
    assert await db.economy.get_bank_user(USER) == (100_000,)


@pytest.mark.asyncio
async def test_rates_are_independently_configurable(db: DatabaseManager) -> None:
    await _set_equal_balances(db, 10_000)

    await _decay(db, wallet_rate=0.02, bank_rate=0.005)._process_decay(3_000)

    assert await db.economy.get_user_currency(USER) == 9_800
    assert await db.economy.get_bank_user(USER) == (9_950,)
