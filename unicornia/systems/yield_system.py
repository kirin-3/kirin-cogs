"""Restart-safe scheduling for stockholder yield distributions."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..database import DatabaseManager
from ..db.economy import DividendRunOutcome


class YieldSystem:
    """Coordinates persisted dividend scheduling without owning money movement."""

    def __init__(self, db: DatabaseManager, config):
        self.db = db
        self.config = config

    async def period_seconds(self) -> int:
        raw_hours = await self.config.dividend_period_hours()
        try:
            hours = int(raw_hours)
        except (TypeError, ValueError):
            hours = 168
        return max(1, hours) * 3600

    async def run_scheduled_distribution(self, now: datetime | None = None) -> tuple[float, DividendRunOutcome | None]:
        """Run a due period and return the delay until the next check."""
        current = now or datetime.utcnow()
        period = await self.period_seconds()
        next_at = await self.db.economy.get_or_initialize_next_distribution(period, current)
        if current < next_at:
            return (next_at - current).total_seconds(), None

        period_start = await self.db.economy.get_dividend_accumulation_start(next_at - timedelta(seconds=period))
        outcome = await self.db.economy.distribute_dividends(
            period_start=period_start,
            period_end=next_at,
            next_distribution_at=next_at + timedelta(seconds=period),
        )
        following = next_at + timedelta(seconds=period)
        return max(1.0, (following - current).total_seconds()), outcome
