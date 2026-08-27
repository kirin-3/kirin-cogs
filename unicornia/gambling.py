"""Pure gambling payout rules shared by live games and RTP tests."""

from __future__ import annotations

import random
from decimal import ROUND_CEILING, Decimal

RTP_TARGET = 0.975
RAKEBACK_RATE = 0.05

_TARGET_SCALE = RTP_TARGET / 0.975


def pooled_rake(total_stake: int, losing_stake: int) -> int:
    """Return the target-derived rake for a pooled-stake settlement.

    The rakeback term must remain inside the rake.  With total stake ``T``
    and losing stake ``L``, participants receive ``T - rake + rL``.  Using
    ``ceil(T(1-target) + rL)`` therefore keeps returned value at or just below
    ``target * T`` after integer rounding instead of adding rakeback on top.
    """
    if total_stake < 0 or losing_stake < 0 or losing_stake > total_stake:
        raise ValueError("Stake totals must satisfy 0 <= losing <= total.")
    value = Decimal(total_stake) * (Decimal(1) - Decimal(str(RTP_TARGET)))
    value += Decimal(losing_stake) * Decimal(str(RAKEBACK_RATE))
    return int(value.to_integral_value(rounding=ROUND_CEILING))


BETFLIP_WIN_MULTIPLIER = 1.90 * _TARGET_SCALE
RPS_WIN_MULTIPLIER = 1.875 * _TARGET_SCALE
LUCKY_LADDER_MULTIPLIERS = tuple(value * _TARGET_SCALE for value in (2.35, 1.67, 1.47, 1.08, 0.49, 0.29, 0.20, 0.10))
MINES_EDGE_FACTOR = RTP_TARGET - RAKEBACK_RATE
BLACKJACK_NATURAL_MULTIPLIER = 2.61 * _TARGET_SCALE


def slots_multiplier(first: int, second: int, third: int) -> float:
    """Return the payout multiplier for three slot reel values."""
    rolls = (first, second, third)
    if first == second == third == 9:
        return 150.0 * _TARGET_SCALE
    if first == second == third:
        return 20.0 * _TARGET_SCALE
    if rolls.count(9) == 2:
        return 5.0 * _TARGET_SCALE
    if rolls.count(9) == 1:
        return 1.95 * _TARGET_SCALE
    return 0.0


def slots_win_type(first: int, second: int, third: int) -> str:
    """Return the display category for three slot reel values."""
    rolls = (first, second, third)
    if first == second == third == 9:
        return "triple_joker"
    if first == second == third:
        return "triple_normal"
    if rolls.count(9) == 2:
        return "double_joker"
    if rolls.count(9) == 1:
        return "single_joker"
    return "lose"


def betroll_multiplier(roll: int) -> float:
    """Return the tiered betroll multiplier for a roll from 1 through 100."""
    if not 1 <= roll <= 100:
        raise ValueError("Betroll result must be between 1 and 100.")
    if roll == 100:
        return 10.0 * _TARGET_SCALE
    if roll > 90:
        return 4.0 * _TARGET_SCALE
    if roll > 66:
        return 2.0 * _TARGET_SCALE
    return 0.0


def betflip_multiplier(won: bool) -> float:
    """Return the betflip multiplier for the resolved win state."""
    return BETFLIP_WIN_MULTIPLIER if won else 0.0


def rps_multiplier(outcome: str) -> float:
    """Return the RPS multiplier for ``win``, ``draw``, or ``lose``."""
    if outcome == "win":
        return RPS_WIN_MULTIPLIER
    if outcome == "draw":
        return 1.0
    if outcome == "lose":
        return 0.0
    raise ValueError(f"Unknown RPS outcome: {outcome}")


def lucky_ladder_multiplier(rung: int) -> float:
    """Return the multiplier for a zero-based lucky-ladder rung."""
    if not 0 <= rung < len(LUCKY_LADDER_MULTIPLIERS):
        raise ValueError("Lucky ladder rung must be between 0 and 7.")
    return LUCKY_LADDER_MULTIPLIERS[rung]


def mines_fair_multiplier(total_cells: int, mines: int, revealed: int) -> float:
    """Return the inverse survival probability at a mines cash-out depth."""
    if total_cells <= 1 or not 1 <= mines < total_cells:
        raise ValueError("Mines must be between 1 and total_cells - 1.")
    safe_cells = total_cells - mines
    if not 0 <= revealed <= safe_cells:
        raise ValueError("Revealed cells must be between 0 and the safe-cell count.")

    multiplier = 1.0
    for index in range(revealed):
        multiplier *= (total_cells - index) / (safe_cells - index)
    return multiplier


def mines_multiplier(total_cells: int, mines: int, revealed: int) -> float:
    """Return the house-adjusted mines multiplier."""
    if revealed == 0:
        return 1.0
    return MINES_EDGE_FACTOR * mines_fair_multiplier(total_cells, mines, revealed)


def calculate_blackjack_hand(hand: list[int]) -> int:
    """Calculate a blackjack hand total with soft aces."""
    total = sum(hand)
    aces = hand.count(11)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def blackjack_natural_multiplier(player: list[int], dealer: list[int]) -> float | None:
    """Resolve opening naturals, or return ``None`` for normal play."""
    player_natural = len(player) == 2 and calculate_blackjack_hand(player) == 21
    dealer_natural = len(dealer) == 2 and calculate_blackjack_hand(dealer) == 21
    if player_natural:
        return 1.0 if dealer_natural else BLACKJACK_NATURAL_MULTIPLIER
    if dealer_natural:
        return 0.0
    return None


def simulate_blackjack_net_rtp(*, seed: int, hands: int) -> float:
    """Simulate hit-to-17 blackjack deterministically for RTP verification."""
    if hands <= 0:
        raise ValueError("Hands must be positive.")

    rng = random.Random(seed)
    base_deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4
    total_return = 0.0

    for _ in range(hands):
        deck = base_deck.copy()
        rng.shuffle(deck)
        player = [deck.pop(), deck.pop()]
        dealer = [deck.pop(), deck.pop()]
        natural_multiplier = blackjack_natural_multiplier(player, dealer)

        if natural_multiplier is not None:
            payout = natural_multiplier
        else:
            while calculate_blackjack_hand(player) < 17:
                player.append(deck.pop())
            player_total = calculate_blackjack_hand(player)

            if player_total > 21:
                payout = 0.0
            else:
                while calculate_blackjack_hand(dealer) < 17:
                    dealer.append(deck.pop())
                dealer_total = calculate_blackjack_hand(dealer)
                if dealer_total > 21 or player_total > dealer_total:
                    payout = 2.0
                elif player_total == dealer_total:
                    payout = 1.0
                else:
                    payout = 0.0

        total_return += payout + RAKEBACK_RATE * max(0.0, 1.0 - payout)

    return total_return / hands
