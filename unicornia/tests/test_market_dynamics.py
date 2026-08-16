"""Pure mean-reverting stock-price model tests."""

from __future__ import annotations

import math
import random

import pytest

from unicornia.stock_market import (
    ALPHA,
    MAX_TICK_MOVE,
    P_BASE,
    P_MAX,
    P_MIN,
    fair_values,
    market_price_step,
    update_smoothed_usage,
)


def test_price_one_rises_from_model_dynamics() -> None:
    price = 1.0
    for _ in range(10):
        price = market_price_step(price, P_BASE, noise=0.0)
    assert price > 1.0


@pytest.mark.parametrize("start", [1.0, 5.0, 10.0, 25.0, 50.0, 100.0])
def test_no_absorbing_starting_price(start: float) -> None:
    price = start
    for _ in range(50):
        price = market_price_step(price, P_BASE, noise=0.25)
    assert price != start


def test_prices_revert_from_both_directions() -> None:
    assert market_price_step(1_000.0, 100.0) < 1_000.0
    assert market_price_step(10.0, 100.0) > 10.0


def test_constant_usage_converges_to_finite_level() -> None:
    smoothed = [0.0, 0.0]
    price = 10.0
    target = P_BASE
    for _ in range(2_000):
        smoothed = [update_smoothed_usage(smoothed[0], 20), update_smoothed_usage(smoothed[1], 5)]
        target = fair_values(smoothed)[0]
        price = market_price_step(price, target)
    assert price == pytest.approx(target, rel=1e-8)
    assert P_MIN <= price <= P_MAX


def test_proportional_floor_is_exactly_scale_invariant() -> None:
    assert fair_values([10.0, 30.0]) == fair_values([20.0, 60.0])


def test_zero_usage_stock_keeps_finite_fair_value() -> None:
    expected = P_BASE * (ALPHA / (1.0 + ALPHA)) ** 0.7
    assert fair_values([0.0, 100.0])[0] == pytest.approx(expected)


def test_all_zero_usage_stays_at_base() -> None:
    assert fair_values([0.0, 0.0, 0.0]) == (P_BASE, P_BASE, P_BASE)


def test_one_quiet_tick_only_slightly_changes_popular_fair_value() -> None:
    before = fair_values([100.0, 10.0])[0]
    after_smoothed = [update_smoothed_usage(100.0, 0), update_smoothed_usage(10.0, 10)]
    after = fair_values(after_smoothed)[0]
    assert abs(after / before - 1.0) < 0.02


def test_long_simulation_respects_bounds_and_tick_clamp() -> None:
    rng = random.Random(8675309)
    prices = [1.0, 100.0, 999_999.0]
    smoothed = [0.0, 0.0, 0.0]
    maximum_factor = 1.0 + MAX_TICK_MOVE
    for _ in range(20_000):
        usages = [rng.randrange(0, 100) for _ in prices]
        smoothed = [update_smoothed_usage(old, usage) for old, usage in zip(smoothed, usages, strict=True)]
        targets = fair_values(smoothed)
        event = rng.choice((0.88, 1.0, 1.0, 1.0, 1.12))
        for index, (price, target) in enumerate(zip(prices, targets, strict=True)):
            updated = market_price_step(price, target, noise=rng.gauss(0, 1), event_multiplier=event)
            assert P_MIN <= updated <= P_MAX
            assert updated / price <= maximum_factor + 1e-12
            assert updated / price >= 1.0 / maximum_factor - 1e-12
            prices[index] = updated


def test_event_shock_decays_toward_fair_value() -> None:
    shocked = market_price_step(P_BASE, P_BASE, event_multiplier=1.12)
    price = shocked
    for _ in range(100):
        price = market_price_step(price, P_BASE)
    assert abs(price - P_BASE) < abs(shocked - P_BASE)
    assert math.isclose(price, P_BASE, rel_tol=1e-3)
