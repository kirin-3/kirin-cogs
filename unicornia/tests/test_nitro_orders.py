"""Nitro purchases keep a durable order until staff have been told about it."""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from unicornia.db.economy import OUTCOME_INSUFFICIENT_FUNDS, OUTCOME_SETTLED
from unicornia.systems.nitro_system import NitroSystem

BUYER = 41


class _Value:
    def __init__(self, store: dict, key: str) -> None:
        self.store = store
        self.key = key

    def __call__(self) -> _Value:
        return self

    def __await__(self):
        async def read() -> Any:
            return copy.deepcopy(self.store[self.key])

        return read().__await__()

    async def __aenter__(self) -> Any:
        return self.store[self.key]

    async def __aexit__(self, *_: object) -> None:
        return None


class _Config:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    def register_global(self, **defaults: Any) -> None:
        self.store.update(copy.deepcopy(defaults))

    def __getattr__(self, key: str) -> _Value:
        return _Value(self.store, key)


def _system(stock: int = 1, wallet: int = 1_000_000) -> tuple[NitroSystem, _Config, MagicMock]:
    config = _Config()
    economy = MagicMock()
    economy.get_balance = AsyncMock(return_value=(wallet, 0))
    economy.db.economy.apply_operation = AsyncMock(return_value=SimpleNamespace(state=OUTCOME_SETTLED))
    economy.db.economy.get_operation = AsyncMock(return_value={"State": "settled"})
    nitro = NitroSystem(config, MagicMock(), economy)  # type: ignore[arg-type]
    config.store["nitro_stock"]["boost"] = stock
    return nitro, config, economy


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.author.id = BUYER
    return ctx


@pytest.mark.asyncio
async def test_failed_notification_keeps_the_paid_order_until_reconciled() -> None:
    nitro, config, economy = _system()
    nitro._notify_purchase = AsyncMock(return_value=False)  # type: ignore[method-assign]

    ok, _ = await nitro.purchase_nitro(_ctx(), "boost")

    assert ok is True
    assert config.store["nitro_stock"]["boost"] == 0
    [order] = config.store["nitro_orders"].values()
    assert order["user_id"] == BUYER and order["item"] == "boost" and order["price"] == 250000
    key = economy.db.economy.apply_operation.await_args.kwargs["key"]

    nitro._notify_purchase = AsyncMock(return_value=True)  # type: ignore[method-assign]
    await nitro.reconcile()

    economy.db.economy.get_operation.assert_awaited_once_with(key)
    nitro._notify_purchase.assert_awaited_once()
    assert config.store["nitro_orders"] == {}
    assert config.store["nitro_stock"]["boost"] == 0


@pytest.mark.asyncio
async def test_unpaid_purchase_puts_the_stock_back() -> None:
    nitro, config, economy = _system()
    economy.db.economy.apply_operation.return_value = SimpleNamespace(state=OUTCOME_INSUFFICIENT_FUNDS)
    nitro._notify_purchase = AsyncMock(return_value=True)  # type: ignore[method-assign]

    ok, _ = await nitro.purchase_nitro(_ctx(), "boost")

    assert ok is False
    assert config.store["nitro_orders"] == {}
    assert config.store["nitro_stock"]["boost"] == 1
    nitro._notify_purchase.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_cancels_an_order_that_was_never_paid() -> None:
    """A crash between recording the order and charging for it."""
    nitro, config, economy = _system(stock=0)
    config.store["nitro_orders"]["abc"] = {"user_id": BUYER, "item": "boost", "price": 250000, "at": 0}
    economy.db.economy.get_operation.return_value = None
    nitro._notify_purchase = AsyncMock(return_value=True)  # type: ignore[method-assign]

    await nitro.reconcile()

    assert config.store["nitro_orders"] == {}
    assert config.store["nitro_stock"]["boost"] == 1
    nitro._notify_purchase.assert_not_awaited()
