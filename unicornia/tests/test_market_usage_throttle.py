"""Tests for the per-user, per-stock emoji usage throttle."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import unicornia.systems.market_system as market_module
from unicornia.systems.market_system import USAGE_THROTTLE_SECONDS, MarketSystem


class _Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _market() -> MarketSystem:
    system = MarketSystem(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    system.emoji_map = {"🦄": "UNI", "🌈": "RBW"}
    system._update_regex()
    assert isinstance(system.regex_pattern, re.Pattern)
    return system


def _message(user_id: int, content: str, *, bot: bool = False) -> Any:
    return SimpleNamespace(author=SimpleNamespace(id=user_id, bot=bot), content=content)


@pytest.fixture
def clock():
    fake = _Clock()
    with patch.object(market_module.time, "monotonic", fake):
        yield fake


@pytest.mark.asyncio
async def test_repeated_emoji_in_one_message_counts_once(clock: _Clock) -> None:
    market = _market()

    await market.process_message(_message(1, "🦄🦄🦄 🦄"))

    assert market.emoji_buffer["UNI"] == 1


@pytest.mark.asyncio
async def test_rapid_messages_count_once_within_window(clock: _Clock) -> None:
    market = _market()

    for _ in range(10):
        await market.process_message(_message(1, "🦄"))
        clock.now += 5

    assert market.emoji_buffer["UNI"] == 1


@pytest.mark.asyncio
async def test_use_after_window_counts_again(clock: _Clock) -> None:
    market = _market()

    await market.process_message(_message(1, "🦄"))
    clock.now += USAGE_THROTTLE_SECONDS - 0.1
    await market.process_message(_message(1, "🦄"))
    clock.now += 0.1
    await market.process_message(_message(1, "🦄"))

    assert market.emoji_buffer["UNI"] == 2


@pytest.mark.asyncio
async def test_two_stocks_in_one_message_each_count(clock: _Clock) -> None:
    market = _market()

    await market.process_message(_message(1, "🦄🌈🦄🌈"))

    assert market.emoji_buffer == {"UNI": 1, "RBW": 1}


@pytest.mark.asyncio
async def test_two_users_are_throttled_independently(clock: _Clock) -> None:
    market = _market()

    await market.process_message(_message(1, "🦄"))
    await market.process_message(_message(2, "🦄"))
    await market.process_message(_message(1, "🦄"))

    assert market.emoji_buffer["UNI"] == 2


@pytest.mark.asyncio
async def test_bots_are_not_counted(clock: _Clock) -> None:
    market = _market()

    await market.process_message(_message(1, "🦄", bot=True))

    assert market.emoji_buffer["UNI"] == 0
    assert market._usage_last_counted == {}


@pytest.mark.asyncio
async def test_market_tick_prunes_expired_entries(clock: _Clock) -> None:
    market = _market()
    await market.process_message(_message(1, "🦄"))
    clock.now += USAGE_THROTTLE_SECONDS + 1
    await market.process_message(_message(2, "🌈"))
    market.stocks_cache = {}
    market.set_last_market_tick = AsyncMock()  # type: ignore[method-assign]

    await market.market_tick()

    assert set(market._usage_last_counted) == {(2, "RBW")}


@pytest.mark.asyncio
async def test_map_stays_bounded_between_ticks(clock: _Clock) -> None:
    market = _market()
    cap = market_module.USAGE_THROTTLE_SOFT_CAP

    for user_id in range(cap + 1):
        await market.process_message(_message(user_id, "🦄"))
    assert len(market._usage_last_counted) == cap + 1

    clock.now += USAGE_THROTTLE_SECONDS + 1
    await market.process_message(_message(cap + 5, "🦄"))

    assert set(market._usage_last_counted) == {(cap + 5, "UNI")}
