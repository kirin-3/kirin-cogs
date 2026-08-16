"""Exact and deterministic verification of Unicornia gambling paytables."""

from __future__ import annotations

import itertools
import math
import time

import pytest

from unicornia.gambling import (
    BLACKJACK_NATURAL_MULTIPLIER,
    RAKEBACK_RATE,
    RTP_TARGET,
    betflip_multiplier,
    betroll_multiplier,
    blackjack_natural_multiplier,
    lucky_ladder_multiplier,
    mines_multiplier,
    rps_multiplier,
    simulate_blackjack_net_rtp,
    slots_multiplier,
)

RTP_TOLERANCE = 0.005


def net_rtp(payouts: list[float]) -> float:
    """Return average payout plus rakeback on realized net loss."""
    return sum(payout + RAKEBACK_RATE * max(0.0, 1.0 - payout) for payout in payouts) / len(payouts)


def _rps_outcome(player: int, bot: int) -> str:
    if player == bot:
        return "draw"
    return "win" if (player - bot) % 3 == 1 else "lose"


def _enumerated_rtps() -> dict[str, float]:
    return {
        "slots": net_rtp([slots_multiplier(*rolls) for rolls in itertools.product(range(10), repeat=3)]),
        "betroll": net_rtp([betroll_multiplier(roll) for roll in range(1, 101)]),
        "rps": net_rtp(
            [rps_multiplier(_rps_outcome(player, bot)) for player, bot in itertools.product(range(3), repeat=2)]
        ),
        "lucky_ladder": net_rtp([lucky_ladder_multiplier(rung) for rung in range(8)]),
        "betflip": net_rtp([betflip_multiplier(False), betflip_multiplier(True)]),
    }


def test_enumerated_games_match_target_and_run_quickly() -> None:
    started = time.perf_counter()
    measured = _enumerated_rtps()
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    for game, rtp in measured.items():
        assert rtp == pytest.approx(RTP_TARGET, abs=RTP_TOLERANCE), f"{game} net RTP was {rtp:.6f}"


def test_mines_every_strategy_is_bounded_by_target() -> None:
    measured: list[float] = []
    total_cells = 20
    for mines in range(1, total_cells):
        safe_cells = total_cells - mines
        for revealed in range(1, safe_cells + 1):
            survival = math.comb(safe_cells, revealed) / math.comb(total_cells, revealed)
            payout = mines_multiplier(total_cells, mines, revealed)
            expected_payout = survival * payout
            expected_loss = (1.0 - survival) + survival * max(0.0, 1.0 - payout)
            rtp = expected_payout + RAKEBACK_RATE * expected_loss
            measured.append(rtp)
            assert rtp <= RTP_TARGET + 1e-12, f"mines={mines}, revealed={revealed}, net RTP={rtp:.6f}"

    assert max(measured) == pytest.approx(RTP_TARGET, abs=RTP_TOLERANCE)


def test_blackjack_seeded_monte_carlo_is_deterministic_and_on_target() -> None:
    first = simulate_blackjack_net_rtp(seed=8_675_309, hands=500_000)
    second = simulate_blackjack_net_rtp(seed=8_675_309, hands=500_000)

    assert first == second
    assert first == pytest.approx(RTP_TARGET, abs=0.01), f"blackjack net RTP was {first:.6f}"


def test_blackjack_opening_naturals_and_equal_total_push() -> None:
    assert blackjack_natural_multiplier([11, 10], [11, 10]) == 1.0
    assert blackjack_natural_multiplier([11, 10], [10, 9]) == BLACKJACK_NATURAL_MULTIPLIER
    assert blackjack_natural_multiplier([10, 9], [11, 10]) == 0.0
    assert blackjack_natural_multiplier([10, 9], [10, 9]) is None
