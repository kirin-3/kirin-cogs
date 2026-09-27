"""The unicorn stable: an idle game where unicorns earn coins into a box while their owner is away.

Coins accrue from timestamps whenever the stable is read or changed, so there is no background loop. Every
change runs in one transaction on Unicornia's connection, which also serializes it against other economy writes.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any

import discord
from redbot.core import Config

from ..database import DatabaseManager


@dataclass(frozen=True)
class Rarity:
    name: str
    weight: int  # hatch chance, out of the weights' sum
    rate: int  # coins a day per level
    color: tuple[int, int, int]


@dataclass(frozen=True)
class Breed:
    name: str
    rarity: str


RARITIES = {
    "common": Rarity("Common", 50, 10, (154, 165, 177)),
    "uncommon": Rarity("Uncommon", 28, 14, (76, 175, 80)),
    "rare": Rarity("Rare", 15, 18, (46, 134, 222)),
    "epic": Rarity("Epic", 6, 25, (155, 89, 182)),
    "legendary": Rarity("Legendary", 1, 35, (241, 196, 15)),
}
BREEDS = {
    "cotton": Breed("Cotton", "common"),
    "hazel": Breed("Hazel", "common"),
    "bluebell": Breed("Bluebell", "uncommon"),
    "clover": Breed("Clover", "uncommon"),
    "rosequartz": Breed("Rose Quartz", "rare"),
    "twilight": Breed("Twilight", "rare"),
    "ember": Breed("Ember", "epic"),
    "frost": Breed("Frost", "epic"),
    "celestial": Breed("Celestial", "legendary"),
    "prism": Breed("Prism", "legendary"),
}
MAX_UNICORNS = 10  # what the card has room for
MAX_LEVEL = 10
MAX_NAME = 20
# (hours the coin box holds, price to reach this size)
BOX_SIZES = ((8, 0), (12, 5_000), (16, 15_000), (24, 40_000))
DEFAULT_SETTINGS: dict[str, float] = {
    "egg_price": 1_000,  # the first egg; each owned unicorn multiplies it by egg_growth
    "egg_growth": 1.3,
    "level_price": 100,  # level 1 -> 2; each level multiplies it by level_growth
    "level_growth": 1.4,
    "earn_rate": 1.0,  # multiplies every unicorn's earnings
}
DAY = 86_400


@dataclass(frozen=True)
class Unicorn:
    id: int
    breed: str
    level: int
    name: str | None

    @property
    def rarity(self) -> Rarity:
        return RARITIES[BREEDS[self.breed].rarity]

    @property
    def label(self) -> str:
        return self.name or BREEDS[self.breed].name

    @property
    def safe_label(self) -> str:
        """The label for a Discord message, where a member's name mustn't turn into formatting."""
        return discord.utils.escape_markdown(self.label)


@dataclass(frozen=True)
class StableState:
    unicorns: list[Unicorn]
    box: float  # coins waiting to be collected
    box_size: int  # index into BOX_SIZES
    per_day: float
    settings: dict[str, float]

    @property
    def box_hours(self) -> int:
        return BOX_SIZES[self.box_size][0]

    @property
    def capacity(self) -> float:
        return self.per_day * self.box_hours / 24

    @property
    def egg_price(self) -> int | None:
        if len(self.unicorns) >= MAX_UNICORNS:
            return None
        return round(self.settings["egg_price"] * self.settings["egg_growth"] ** len(self.unicorns))

    @property
    def next_box(self) -> tuple[int, int] | None:
        """(hours, price) of the next coin box size, None at the largest."""
        return BOX_SIZES[self.box_size + 1] if self.box_size + 1 < len(BOX_SIZES) else None

    def level_price(self, unicorn: Unicorn) -> int | None:
        if unicorn.level >= MAX_LEVEL:
            return None
        return round(self.settings["level_price"] * self.settings["level_growth"] ** (unicorn.level - 1))


def daily_rate(unicorns: list[Unicorn], earn_rate: float) -> float:
    return sum(u.rarity.rate * u.level for u in unicorns) * earn_rate


def settle(box: float, elapsed: float, per_day: float, box_hours: int) -> float:
    """The box after `elapsed` seconds of earning. It stops at its capacity but never loses coins,
    even when the capacity shrank since (a released unicorn)."""
    capacity = per_day * box_hours / 24
    return max(box, min(capacity, box + per_day * max(elapsed, 0.0) / DAY))


def roll_breed(rng: random.Random) -> str:
    (rarity,) = rng.choices(list(RARITIES), weights=[r.weight for r in RARITIES.values()])
    return rng.choice([key for key, breed in BREEDS.items() if breed.rarity == rarity])


def clean_settings(raw: Any) -> dict[str, float]:
    """Settings from Config, falling back to the defaults for anything missing or unusable."""
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        for key in settings:
            value = raw.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
                settings[key] = float(value)
    return settings


class StableSystem:
    def __init__(self, db: DatabaseManager, config: Config, *, rng: random.Random | None = None):
        self.db = db
        self.config = config
        self.rng = rng or random.Random()

    async def settings(self) -> dict[str, float]:
        return clean_settings(await self.config.stable_settings())

    async def _load(self, conn, user_id: int, now: float, settings: dict[str, float]) -> StableState:
        """Read the stable and settle its box up to now, inside the caller's transaction."""
        cursor = await conn.execute(
            "SELECT Id, Breed, Level, Name FROM StableUnicorn WHERE UserId = ? ORDER BY Id", (user_id,)
        )
        unicorns = [Unicorn(*row) for row in await cursor.fetchall() if row[1] in BREEDS]
        cursor = await conn.execute("SELECT Box, LastSettle, BoxSize FROM Stable WHERE UserId = ?", (user_id,))
        row = await cursor.fetchone()
        box, last, box_size = row if row else (0.0, now, 0)
        box_size = min(max(int(box_size), 0), len(BOX_SIZES) - 1)
        per_day = daily_rate(unicorns, settings["earn_rate"])
        box = settle(float(box), now - float(last), per_day, BOX_SIZES[box_size][0])
        return StableState(unicorns, box, box_size, per_day, settings)

    @staticmethod
    async def _save(conn, user_id: int, now: float, box: float, box_size: int) -> None:
        await conn.execute(
            """
            INSERT INTO Stable (UserId, Box, LastSettle, BoxSize) VALUES (?, ?, ?, ?)
            ON CONFLICT(UserId) DO UPDATE SET
                Box = excluded.Box, LastSettle = excluded.LastSettle, BoxSize = excluded.BoxSize
            """,
            (user_id, box, now, box_size),
        )

    async def state(self, user_id: int, *, now: float | None = None) -> StableState:
        now = time.time() if now is None else now
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            return await self._load(conn, user_id, now, settings)

    async def collect(self, user_id: int, *, now: float | None = None) -> int:
        """Pay out the box's whole coins; returns how many."""
        now = time.time() if now is None else now
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            await conn.execute("BEGIN")
            state = await self._load(conn, user_id, now, settings)
            paid = int(state.box)
            if paid > 0:
                await self.db.economy._add_currency(user_id, paid, "stable_collect", "", None, "Stable coin box", conn)
            await self._save(conn, user_id, now, state.box - paid, state.box_size)
            await conn.commit()
            return paid

    async def _buy(self, conn, user_id: int, price: int, kind: str, note: str) -> bool:
        return await self.db.economy._remove_currency(user_id, price, kind, "", None, note, conn)

    async def hatch(self, user_id: int, *, now: float | None = None) -> tuple[str | None, str]:
        """Buy and hatch an egg. Returns (breed, message); breed is None when nothing was bought."""
        now = time.time() if now is None else now
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            await conn.execute("BEGIN")
            state = await self._load(conn, user_id, now, settings)
            price = state.egg_price
            if price is None:
                await conn.rollback()
                return None, f"Your stable is full ({MAX_UNICORNS} unicorns). Release one to make room."
            if not await self._buy(conn, user_id, price, "stable_egg", "Stable egg"):
                await conn.commit()
                return None, f"An egg costs **{price:,}** and you don't have enough in your wallet."
            breed = roll_breed(self.rng)
            await conn.execute("INSERT INTO StableUnicorn (UserId, Breed) VALUES (?, ?)", (user_id, breed))
            # Earnings so far stay at the old rate; the newcomer earns from now on
            await self._save(conn, user_id, now, state.box, state.box_size)
            await conn.commit()
        rarity = RARITIES[BREEDS[breed].rarity]
        return breed, f"🥚 The egg hatched into **{BREEDS[breed].name}**, a {rarity.name.lower()} unicorn!"

    async def upgrade(self, user_id: int, unicorn_id: int, *, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            await conn.execute("BEGIN")
            state = await self._load(conn, user_id, now, settings)
            unicorn = next((u for u in state.unicorns if u.id == unicorn_id), None)
            if unicorn is None:
                await conn.rollback()
                return False, "That unicorn isn't in your stable any more."
            price = state.level_price(unicorn)
            if price is None:
                await conn.rollback()
                return False, f"**{unicorn.safe_label}** is already level {MAX_LEVEL}."
            if not await self._buy(conn, user_id, price, "stable_upgrade", "Stable unicorn level"):
                await conn.commit()
                return False, f"Level {unicorn.level + 1} costs **{price:,}** and you don't have enough in your wallet."
            await conn.execute("UPDATE StableUnicorn SET Level = Level + 1 WHERE Id = ?", (unicorn.id,))
            await self._save(conn, user_id, now, state.box, state.box_size)
            await conn.commit()
        return True, f"⬆️ **{unicorn.safe_label}** is now level {unicorn.level + 1}."

    async def upgrade_box(self, user_id: int, *, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            await conn.execute("BEGIN")
            state = await self._load(conn, user_id, now, settings)
            if state.next_box is None:
                await conn.rollback()
                return False, "Your coin box is already the biggest there is."
            hours, price = state.next_box
            if not await self._buy(conn, user_id, price, "stable_box", "Stable coin box"):
                await conn.commit()
                return False, f"A {hours}-hour coin box costs **{price:,}** and you don't have enough in your wallet."
            await self._save(conn, user_id, now, state.box, state.box_size + 1)
            await conn.commit()
        return True, f"📦 Your coin box now holds {hours} hours of earnings."

    async def rename(self, user_id: int, slot: int, name: str | None) -> tuple[bool, str]:
        state = await self.state(user_id)
        if not 1 <= slot <= len(state.unicorns):
            return False, f"You don't have a unicorn #{slot}."
        unicorn = state.unicorns[slot - 1]
        async with self.db._get_connection() as conn:
            await conn.execute("UPDATE StableUnicorn SET Name = ? WHERE Id = ?", (name, unicorn.id))
            await conn.commit()
        return True, f"#{slot} is now called **{discord.utils.escape_markdown(name or BREEDS[unicorn.breed].name)}**."

    async def release(self, user_id: int, unicorn_id: int, *, now: float | None = None) -> bool:
        """Let a unicorn go, keeping what it has already earned in the box."""
        now = time.time() if now is None else now
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            await conn.execute("BEGIN")
            state = await self._load(conn, user_id, now, settings)
            cursor = await conn.execute("DELETE FROM StableUnicorn WHERE Id = ? AND UserId = ?", (unicorn_id, user_id))
            await self._save(conn, user_id, now, state.box, state.box_size)
            await conn.commit()
            return cursor.rowcount > 0

    async def top(self, user_ids: set[int], limit: int = 10) -> list[tuple[int, float]]:
        """The stables earning most per day among `user_ids`."""
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            cursor = await conn.execute("SELECT UserId, Breed, Level FROM StableUnicorn")
            rows = await cursor.fetchall()
        totals: dict[int, float] = {}
        for user_id, breed, level in rows:
            if user_id in user_ids and breed in BREEDS:
                totals[user_id] = totals.get(user_id, 0.0) + RARITIES[BREEDS[breed].rarity].rate * level
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
        return [(user_id, total * settings["earn_rate"]) for user_id, total in ranked]
