"""Counts of completed roleplay actions between two members, for [p]rpstats and the member site.

Stored per (doer, receiver) pair: ``{"counts": {action name: times}}``. Members with the Untracked setting on are
never counted, and turning it on deletes what was counted for them.
"""

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable

from redbot.core import Config

Pairs = dict[tuple[int, int], Counter[str]]


class Tally:
    def __init__(self, config: Config, untracked: Callable[[int], Awaitable[bool]]) -> None:
        self.config = config
        self.untracked = untracked
        config.init_custom("TALLY", 2)  # doer ID, receiver ID
        config.register_custom("TALLY", counts={})
        # ponytail: one lock for every pair; actions are rate-limited per channel, so contention is tiny
        self.lock = asyncio.Lock()

    async def record(self, doer_id: int, receiver_id: int, action: str) -> None:
        # The Untracked check is inside the lock, so a count can't land after an opt-out has deleted the old ones
        async with self.lock:
            if doer_id == receiver_id or await self.untracked(doer_id) or await self.untracked(receiver_id):
                return
            async with self.config.custom("TALLY", str(doer_id), str(receiver_id)).counts() as counts:
                current = counts.get(action)
                counts[action] = (current if isinstance(current, int) else 0) + 1

    async def pairs(self) -> Pairs:
        """Every pair's action counts, skipping malformed records."""
        found: Pairs = {}
        stored = await self.config.custom("TALLY").all()
        for doer, receivers in stored.items():
            if not isinstance(receivers, dict):
                continue
            for receiver, record in receivers.items():
                counts = record.get("counts") if isinstance(record, dict) else None
                if not (isinstance(counts, dict) and str(doer).isdigit() and str(receiver).isdigit()):
                    continue
                valid = Counter({str(a): n for a, n in counts.items() if isinstance(n, int) and n > 0})
                if valid:
                    found[int(doer), int(receiver)] = valid
        return found

    async def forget(self, user_id: int) -> None:
        """Delete every count the user is part of, either way round."""
        async with self.lock:
            await self.config.custom("TALLY", str(user_id)).clear()
            for doer, receivers in (await self.config.custom("TALLY").all()).items():
                if isinstance(receivers, dict) and str(user_id) in receivers:
                    await self.config.custom("TALLY", doer, str(user_id)).clear()


def member_stats(pairs: Pairs, user_id: int) -> tuple[Counter[str], Counter[str], Counter[int]]:
    """What the member did, what was done to them, and how many actions they shared with each partner."""
    given: Counter[str] = Counter()
    received: Counter[str] = Counter()
    partners: Counter[int] = Counter()
    for (doer, receiver), counts in pairs.items():
        if doer == user_id:
            given += counts
            partners[receiver] += counts.total()
        if receiver == user_id:
            received += counts
            partners[doer] += counts.total()
    return given, received, partners


def top_pairs(pairs: Pairs, limit: int) -> list[tuple[int, int, Counter[str]]]:
    """The pairs with the most actions between them, either way round, busiest first."""
    together: dict[tuple[int, int], Counter[str]] = {}
    for (doer, receiver), counts in pairs.items():
        together.setdefault((min(doer, receiver), max(doer, receiver)), Counter()).update(counts)
    ranked = sorted(together.items(), key=lambda item: item[1].total(), reverse=True)
    return [(a, b, counts) for (a, b), counts in ranked[:limit]]


def summary(counts: Counter[str], top: int = 3) -> str:
    """``hug **42** · pat **10** · kiss **3**``"""
    return " · ".join(f"{action} **{times:,}**" for action, times in counts.most_common(top))
