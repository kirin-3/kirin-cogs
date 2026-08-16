"""Pure stock-market pricing and unwind planning helpers."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

THETA = 0.08
SIGMA = 0.02
GAMMA = 0.7
LAMBDA = 0.9
ALPHA = 0.5
P_BASE = 100.0
MAX_TICK_MOVE = 0.15
P_MIN = 1.0
P_MAX = 1_000_000.0
INITIAL_SHARE_RESERVE = 100_000.0
TRADE_IMPACT_LIMIT = 0.10


@dataclass(frozen=True, slots=True)
class TradeQuote:
    """The price and reserve state produced by one trade."""

    spot_after: float
    average_execution_price: float
    reserve_after: float


@dataclass(frozen=True, slots=True)
class UnwindRefund:
    """One resolvable holding and its intended cost-basis refund."""

    user_id: int
    symbol: str
    shares: int
    per_share_cost: float
    refund: int


@dataclass(frozen=True, slots=True)
class UnresolvableHolding:
    """A holding whose cost basis cannot be reconstructed safely."""

    user_id: int
    symbol: str
    shares: int


@dataclass(frozen=True, slots=True)
class UnwindPlan:
    """Complete, immutable plan used by dry runs and confirmed unwinds."""

    refunds: tuple[UnwindRefund, ...]
    unresolvable: tuple[UnresolvableHolding, ...]

    @property
    def total_refund(self) -> int:
        return sum(item.refund for item in self.refunds)

    @property
    def users_affected(self) -> int:
        return len({item.user_id for item in self.refunds})


@dataclass(frozen=True, slots=True)
class UnwindOutcome:
    """Result of a dry run, successful execution, or fail-closed abort."""

    plan: UnwindPlan
    executed: bool = False
    aborted: bool = False
    run_id: str | None = None


def update_smoothed_usage(previous: float, usage: int | float) -> float:
    """Advance the persisted usage EMA by one market tick."""
    return LAMBDA * max(0.0, previous) + (1.0 - LAMBDA) * max(0.0, float(usage))


def usage_shares(smoothed_usages: Sequence[float]) -> tuple[float, ...]:
    """Return proportional-floor usage shares that sum to one."""
    count = len(smoothed_usages)
    if count == 0:
        return ()
    sanitized = tuple(max(0.0, float(value)) for value in smoothed_usages)
    total = sum(sanitized)
    if total == 0:
        return (1.0 / count,) * count
    floor = ALPHA * total / count
    denominator = total * (1.0 + ALPHA)
    return tuple((value + floor) / denominator for value in sanitized)


def fair_value(usage_share: float, stock_count: int) -> float:
    """Map one relative usage share to its finite market fair value."""
    if stock_count <= 0:
        raise ValueError("stock_count must be positive")
    if usage_share <= 0:
        raise ValueError("usage_share must be positive")
    return P_BASE * (usage_share * stock_count) ** GAMMA


def fair_values(smoothed_usages: Sequence[float]) -> tuple[float, ...]:
    """Calculate fair values for all tracked stocks."""
    shares = usage_shares(smoothed_usages)
    return tuple(fair_value(share, len(shares)) for share in shares)


def market_price_step(
    current_price: float,
    target_fair_value: float,
    *,
    noise: float = 0.0,
    event_multiplier: float = 1.0,
) -> float:
    """Apply one bounded log-space OU price step.

    The order is deliberate: OU move, event shock, log-move clamp, then
    absolute price bounds.
    """
    if current_price <= 0 or target_fair_value <= 0:
        raise ValueError("prices must be positive")
    if event_multiplier <= 0:
        raise ValueError("event_multiplier must be positive")

    log_move = THETA * (math.log(target_fair_value) - math.log(current_price))
    log_move += SIGMA * noise
    log_move += math.log(event_multiplier)
    max_log_move = math.log1p(MAX_TICK_MOVE)
    log_move = min(max(log_move, -max_log_move), max_log_move)
    stepped = current_price * math.exp(log_move)
    return min(max(stepped, P_MIN), P_MAX)


def buy_quote(price: float, reserve: float, shares: int | float) -> TradeQuote:
    """Price a buy along ``p = A / X`` and reduce the share reserve."""
    amount = float(shares)
    if price <= 0 or reserve <= 0 or amount <= 0 or amount >= reserve:
        raise ValueError("buy inputs must be positive and shares must be below reserve")
    reserve_after = reserve - amount
    ratio = reserve / reserve_after
    return TradeQuote(
        spot_after=price * ratio,
        average_execution_price=price * (reserve / amount) * math.log(ratio),
        reserve_after=reserve_after,
    )


def sell_quote(price: float, reserve: float, shares: int | float) -> TradeQuote:
    """Price a sell along ``p = A / X`` and replenish the share reserve."""
    amount = float(shares)
    if price <= 0 or reserve <= 0 or amount <= 0:
        raise ValueError("sell inputs must be positive")
    reserve_after = reserve + amount
    ratio = reserve_after / reserve
    return TradeQuote(
        spot_after=price / ratio,
        average_execution_price=price * (reserve / amount) * math.log(ratio),
        reserve_after=reserve_after,
    )


def maximum_trade_size(reserve: float, side: str) -> int:
    """Return the largest whole-share trade inside the configured impact band."""
    if reserve <= 0:
        return 0
    if side == "buy":
        limit = TRADE_IMPACT_LIMIT * reserve
    elif side == "sell":
        limit = TRADE_IMPACT_LIMIT * reserve / (1.0 - TRADE_IMPACT_LIMIT)
    else:
        raise ValueError("side must be 'buy' or 'sell'")
    return max(0, math.floor(limit + 1e-9))


def _ledger_cost_basis(rows: Sequence[Mapping[str, Any]], expected_shares: int) -> float | None:
    """Reconstruct remaining basis by adding buy legs and removing sold basis."""
    held_shares = 0
    basis = 0.0
    for row in rows:
        if str(row.get("kind", "trade")) != "trade":
            continue
        shares = int(row.get("shares") or 0)
        exec_price = float(row.get("exec_price") or 0.0)
        if shares <= 0 or exec_price <= 0:
            return None
        side = str(row.get("side") or "")
        if side == "buy":
            total_amount = abs(int(row.get("total_amount") or 0))
            leg_cost = float(total_amount) if total_amount > 0 else exec_price * shares + int(row.get("tax") or 0)
            basis += leg_cost
            held_shares += shares
        elif side == "sell":
            if shares > held_shares or held_shares <= 0:
                return None
            basis -= (basis / held_shares) * shares
            held_shares -= shares
        else:
            return None
    if held_shares != expected_shares or basis <= 0:
        return None
    return basis


def plan_stock_unwind(
    holdings: Iterable[Mapping[str, Any]],
    ledger_rows: Iterable[Mapping[str, Any]],
) -> UnwindPlan:
    """Build a complete unwind plan without mutating the supplied records."""
    ledger: dict[tuple[int, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in ledger_rows:
        ledger[(int(row["user_id"]), str(row["symbol"]).upper())].append(row)

    refunds: list[UnwindRefund] = []
    unresolvable: list[UnresolvableHolding] = []
    for holding in holdings:
        user_id = int(holding["user_id"])
        symbol = str(holding["symbol"]).upper()
        shares = int(holding["amount"])
        if shares <= 0:
            continue
        recorded_cost = holding.get("average_cost")
        per_share = float(recorded_cost or 0.0)
        refund = round(shares * per_share) if per_share > 0 else 0
        if refund <= 0:
            reconstructed = _ledger_cost_basis(ledger[(user_id, symbol)], shares)
            if reconstructed is not None:
                refund = round(reconstructed)
                per_share = reconstructed / shares
        if refund <= 0:
            unresolvable.append(UnresolvableHolding(user_id, symbol, shares))
            continue
        refunds.append(UnwindRefund(user_id, symbol, shares, per_share, refund))

    return UnwindPlan(tuple(refunds), tuple(unresolvable))
