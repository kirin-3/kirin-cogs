"""The unicorn stable: an idle game where unicorns earn coins into a box while their owner is away.

Coins accrue from timestamps whenever the stable is read or changed, so there is no background loop. Every
change runs in one transaction on Unicornia's connection, which also serializes it against other economy writes.

Past a full stable the game keeps going: shinies, a permanent collection, per-breed perks, ascension and
seasonal eggs. Every bonus folds into one `Modifiers` value, so the card, the buttons, the commands and the
member site all show the same numbers.
"""

from __future__ import annotations

import math
import random
import time
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
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
    # Seasonal breeds hatch only from the season's own roll, never from the rarity roll (weight 0)
    "seasonal": Rarity("Seasonal", 0, 25, (0, 168, 150)),
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
    "pumpkin": Breed("Pumpkin", "seasonal"),
    "yule": Breed("Yule", "seasonal"),
    "sweetheart": Breed("Sweetheart", "seasonal"),
    "pride": Breed("Pride", "seasonal"),
}
REGULAR_BREEDS = frozenset(key for key, breed in BREEDS.items() if breed.rarity != "seasonal")
SEASONAL_BREEDS = frozenset(key for key, breed in BREEDS.items() if breed.rarity == "seasonal")
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

# One perk per regular breed, applied while at least one unicorn of that breed is in the stable
PERK_EARN_CAP = 0.25
SHINY_CHANCE = 1 / 200  # before Bluebell and Prism double it
SHINY_BONUS = 0.10  # what a shiny unicorn earns on top of its breed's rate
COLLECTION_PAIR_BONUS = 0.02  # per completed regular rarity pair
COLLECTION_FULL_BONUS = 0.05  # for discovering all ten regular breeds
COLLECTION_CAP = 0.15
ASCENSION_EARN_BONUS = 0.10  # per ascension
ASCENSION_PRICE_FACTOR = 1.2  # per ascension, on eggs and level-ups


@dataclass(frozen=True)
class Perk:
    description: str
    earn: float = 0.0  # added to the stable's earnings; all earnings perks together cap at PERK_EARN_CAP
    box_hours: int = 0
    egg_discount: float = 0.0
    level_discount: float = 0.0
    free_egg_chance: float = 0.0
    shiny_multiplier: float = 1.0
    rare_weight_factor: float = 1.0


PERKS: dict[str, Perk] = {
    "cotton": Perk("The coin box holds 1 hour more.", box_hours=1),
    "hazel": Perk("Level-ups cost 10% less.", level_discount=0.10),
    "bluebell": Perk("Shiny chance is doubled.", shiny_multiplier=2),
    "clover": Perk("Each egg has a 10% chance to cost nothing.", free_egg_chance=0.10),
    "rosequartz": Perk("Eggs cost 5% less.", egg_discount=0.05),
    "twilight": Perk("The coin box holds 3 hours more.", box_hours=3),
    "ember": Perk("The stable earns 5% more.", earn=0.05),
    "frost": Perk("Rare, epic and legendary hatch chances are 1.5 times as high.", rare_weight_factor=1.5),
    "celestial": Perk("The stable earns 10% more.", earn=0.10),
    "prism": Perk("The stable earns 10% more and shiny chance is doubled.", earn=0.10, shiny_multiplier=2),
}

# Seasonal breeds, their art keys and their UTC hatch windows: (start month, day) to (end month, day),
# both days included in full. Yule's window crosses the new year.
SEASONAL_CHANCE = 0.15  # each hatch's chance to produce the in-season breed
SEASONS: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    "pumpkin": ((10, 1), (11, 2)),
    "yule": ((12, 1), (1, 6)),
    "sweetheart": ((2, 1), (2, 21)),
    "pride": ((6, 1), (6, 30)),
}


def active_season(now: float) -> str | None:
    """The seasonal breed whose UTC hatch window contains `now`, or None outside every season."""
    month, day = datetime.fromtimestamp(now, tz=UTC).timetuple()[1:3]
    today = (month, day)
    for breed, (start, end) in SEASONS.items():
        if start <= end:
            inside = start <= today <= end
        else:  # the window crosses the new year (Yule)
            inside = today >= start or today <= end
        if inside:
            return breed
    return None


@dataclass(frozen=True)
class Unicorn:
    id: int
    breed: str
    level: int
    name: str | None
    shiny: bool = False

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
class Modifiers:
    """Everything the stable's earnings, prices, box size and hatch odds are read through.

    Built by `modifiers()` from the stable's unicorns, discoveries and ascensions, so every screen
    that shows a number computes it through the same value.
    """

    earn_multiplier: float = 1.0
    box_bonus_hours: int = 0
    egg_price_factor: float = 1.0
    level_price_factor: float = 1.0
    free_egg_chance: float = 0.0
    shiny_chance: float = SHINY_CHANCE
    rare_weight_factor: float = 1.0


def collection_bonus(discovered: Collection[str]) -> float:
    """2% per completed regular rarity pair, +5% for all ten regular breeds, capped at 15%.

    Seasonal breeds and shinies don't count: they're for the collection's own sake.
    """
    found = {breed for breed in discovered if breed in REGULAR_BREEDS}
    pairs = sum(
        1
        for rarity in RARITIES
        if rarity != "seasonal" and all(key in found for key, breed in BREEDS.items() if breed.rarity == rarity)
    )
    bonus = COLLECTION_PAIR_BONUS * pairs + (COLLECTION_FULL_BONUS if len(found) >= len(REGULAR_BREEDS) else 0.0)
    return min(bonus, COLLECTION_CAP)


def modifiers(unicorns: list[Unicorn], discovered: Collection[str], ascensions: int) -> Modifiers:
    """Fold the perks of the distinct breeds in the stable, the collection bonus and the ascension bonus."""
    perks = {PERKS[breed] for breed in {u.breed for u in unicorns} if breed in PERKS}
    ascensions = max(int(ascensions), 0)
    shiny_multiplier = math.prod(perk.shiny_multiplier for perk in perks)
    return Modifiers(
        earn_multiplier=1.0
        + collection_bonus(discovered)
        + min(PERK_EARN_CAP, sum(perk.earn for perk in perks))
        + ASCENSION_EARN_BONUS * ascensions,
        box_bonus_hours=sum(perk.box_hours for perk in perks),
        egg_price_factor=ASCENSION_PRICE_FACTOR**ascensions * (1.0 - min(sum(p.egg_discount for p in perks), 0.9)),
        level_price_factor=ASCENSION_PRICE_FACTOR**ascensions * (1.0 - min(sum(p.level_discount for p in perks), 0.9)),
        free_egg_chance=sum(perk.free_egg_chance for perk in perks),
        shiny_chance=SHINY_CHANCE * shiny_multiplier,
        rare_weight_factor=math.prod(perk.rare_weight_factor for perk in perks),
    )


@dataclass(frozen=True)
class StableState:
    unicorns: list[Unicorn]
    box: float  # coins waiting to be collected
    box_size: int  # index into BOX_SIZES
    settings: dict[str, float]
    modifiers: Modifiers = Modifiers()
    ascensions: int = 0
    discovered: frozenset[str] = frozenset()  # breeds ever hatched, regular and seasonal
    shiny_found: frozenset[str] = frozenset()  # breeds ever hatched as a shiny

    @property
    def per_day(self) -> float:
        return daily_rate(self.unicorns, self.settings["earn_rate"], self.modifiers)

    @property
    def found(self) -> int:
        """How many of the ten regular breeds the member has discovered."""
        return len(self.discovered & REGULAR_BREEDS)

    @property
    def box_hours(self) -> int:
        return BOX_SIZES[self.box_size][0] + self.modifiers.box_bonus_hours

    @property
    def capacity(self) -> float:
        return self.per_day * self.box_hours / 24

    @property
    def egg_price(self) -> int | None:
        if len(self.unicorns) >= MAX_UNICORNS:
            return None
        return round(
            self.settings["egg_price"]
            * self.settings["egg_growth"] ** len(self.unicorns)
            * self.modifiers.egg_price_factor
        )

    @property
    def next_box(self) -> tuple[int, int] | None:
        """(hours, price) of the next coin box size, None at the largest."""
        return BOX_SIZES[self.box_size + 1] if self.box_size + 1 < len(BOX_SIZES) else None

    def level_price(self, unicorn: Unicorn) -> int | None:
        if unicorn.level >= MAX_LEVEL:
            return None
        return round(
            self.settings["level_price"]
            * self.settings["level_growth"] ** (unicorn.level - 1)
            * self.modifiers.level_price_factor
        )


def daily_rate(unicorns: list[Unicorn], earn_rate: float, mods: Modifiers = Modifiers()) -> float:
    base = sum(u.rarity.rate * u.level * (1.0 + SHINY_BONUS if u.shiny else 1.0) for u in unicorns)
    return base * mods.earn_multiplier * earn_rate


def settle(box: float, elapsed: float, per_day: float, box_hours: int) -> float:
    """The box after `elapsed` seconds of earning. It stops at its capacity but never loses coins,
    even when the capacity shrank since (a released unicorn)."""
    capacity = per_day * box_hours / 24
    return max(box, min(capacity, box + per_day * max(elapsed, 0.0) / DAY))


def rarity_weights(rare_factor: float = 1.0) -> list[float]:
    """The rarity roll's weights, in RARITIES order.

    `rare_factor` (Frost) multiplies the rare, epic and legendary chances; the common and uncommon
    weights shrink so the boosted chances are exactly that factor of the base ones.
    """
    boosted = ("rare", "epic", "legendary")
    base = {name: rarity.weight for name, rarity in RARITIES.items()}
    boosted_total = sum(base[name] for name in boosted) * rare_factor
    rest = sum(base.values()) - sum(base[name] for name in boosted)
    scale = (sum(base.values()) - boosted_total) / rest if rest else 0.0
    return [float(base[name] * (rare_factor if name in boosted else scale)) for name in RARITIES]


def roll_hatch(rng: random.Random, season: str | None, mods: Modifiers) -> tuple[str, bool]:
    """One hatch: the season's roll first, then the weighted rarity roll, then the independent shiny roll."""
    if season is not None and rng.random() < SEASONAL_CHANCE:
        return season, rng.random() < mods.shiny_chance
    (rarity,) = rng.choices(list(RARITIES), weights=rarity_weights(mods.rare_weight_factor))
    breed = rng.choice([key for key, breed in BREEDS.items() if breed.rarity == rarity])
    return breed, rng.random() < mods.shiny_chance


def clean_settings(raw: Any) -> dict[str, float]:
    """Settings from Config, falling back to the defaults for anything missing or unusable."""
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        for key in settings:
            value = raw.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value) and value > 0:
                settings[key] = float(value)
    return settings


def ascend_problem(state: StableState) -> str | None:
    """Why this stable can't ascend yet, or None when it can."""
    if len(state.unicorns) < MAX_UNICORNS:
        return f"You need {MAX_UNICORNS} unicorns to ascend (you have {len(state.unicorns)})."
    if any(u.level < MAX_LEVEL for u in state.unicorns):
        return f"Every unicorn must be level {MAX_LEVEL} to ascend."
    return None


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
            "SELECT Id, Breed, Level, Name, Shiny FROM StableUnicorn WHERE UserId = ? ORDER BY Id", (user_id,)
        )
        unicorns = [
            Unicorn(unicorn_id, breed, level, name, bool(shiny))
            for unicorn_id, breed, level, name, shiny in await cursor.fetchall()
            if breed in BREEDS
        ]
        cursor = await conn.execute(
            "SELECT Box, LastSettle, BoxSize, Ascensions FROM Stable WHERE UserId = ?", (user_id,)
        )
        row = await cursor.fetchone()
        box, last, box_size, ascensions = row if row else (0.0, now, 0, 0)
        box_size = min(max(int(box_size), 0), len(BOX_SIZES) - 1)
        discovered: set[str] = set()
        shiny_found: set[str] = set()
        cursor = await conn.execute("SELECT Breed, Shiny FROM StableDiscovery WHERE UserId = ?", (user_id,))
        for breed, shiny in await cursor.fetchall():
            if breed in BREEDS:
                discovered.add(breed)
                if shiny:
                    shiny_found.add(breed)
        ascensions = max(int(ascensions), 0)
        mods = modifiers(unicorns, discovered, ascensions)
        per_day = daily_rate(unicorns, settings["earn_rate"], mods)
        box = settle(float(box), now - float(last), per_day, BOX_SIZES[box_size][0] + mods.box_bonus_hours)
        return StableState(
            unicorns, box, box_size, settings, mods, ascensions, frozenset(discovered), frozenset(shiny_found)
        )

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
            # A free egg (Clover) still has to be affordable, so wallet and bank are checked before the free roll
            if await self.db.economy._get_spendable(user_id, conn) < price:
                await conn.rollback()
                return None, f"An egg costs **{price:,}** and you don't have enough in your wallet and bank."
            free = state.modifiers.free_egg_chance > 0 and self.rng.random() < state.modifiers.free_egg_chance
            if not free and not await self._buy(conn, user_id, price, "stable_egg", "Stable egg"):
                await conn.commit()
                return None, f"An egg costs **{price:,}** and you don't have enough in your wallet and bank."
            breed, shiny = roll_hatch(self.rng, active_season(now), state.modifiers)
            await conn.execute(
                "INSERT INTO StableUnicorn (UserId, Breed, Shiny) VALUES (?, ?, ?)", (user_id, breed, int(shiny))
            )
            await conn.execute(
                "INSERT OR IGNORE INTO StableDiscovery (UserId, Breed, Shiny) VALUES (?, ?, 0)", (user_id, breed)
            )
            if shiny:
                await conn.execute(
                    "INSERT OR IGNORE INTO StableDiscovery (UserId, Breed, Shiny) VALUES (?, ?, 1)", (user_id, breed)
                )
            # Earnings so far stay at the old rate; the newcomer earns from now on
            await self._save(conn, user_id, now, state.box, state.box_size)
            await conn.commit()
        rarity = RARITIES[BREEDS[breed].rarity]
        message = f"🥚 The egg hatched into **{BREEDS[breed].name}**, a {rarity.name.lower()} unicorn!"
        if shiny:
            message += " ✨ It's **shiny** — it earns 10% more!"
        if free:
            message += " 🍀 Clover made this egg **free**."
        return breed, message

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
                return (
                    False,
                    f"Level {unicorn.level + 1} costs **{price:,}** and you don't have enough in your wallet and bank.",
                )
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
                return (
                    False,
                    f"A {hours}-hour coin box costs **{price:,}** and you don't have enough in your wallet and bank.",
                )
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
        """Let a unicorn go, keeping what it has already earned in the box.

        The collection is a log of hatches, so releasing never touches it.
        """
        now = time.time() if now is None else now
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            await conn.execute("BEGIN")
            state = await self._load(conn, user_id, now, settings)
            cursor = await conn.execute("DELETE FROM StableUnicorn WHERE Id = ? AND UserId = ?", (unicorn_id, user_id))
            await self._save(conn, user_id, now, state.box, state.box_size)
            await conn.commit()
            return cursor.rowcount > 0

    async def ascend(self, user_id: int, *, now: float | None = None) -> tuple[bool, str]:
        """Ascend a qualifying stable: pay out the box, empty the stalls, count one ascension.

        The coin box size, the collection and the wallet are kept; unicorns and levels are not.
        """
        now = time.time() if now is None else now
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            await conn.execute("BEGIN")
            state = await self._load(conn, user_id, now, settings)
            problem = ascend_problem(state)
            if problem is not None:
                await conn.rollback()
                return False, problem
            paid = int(state.box)
            if paid > 0:
                await self.db.economy._add_currency(user_id, paid, "stable_ascend", "", None, "Stable ascension", conn)
            await conn.execute("DELETE FROM StableUnicorn WHERE UserId = ?", (user_id,))
            await self._save(conn, user_id, now, state.box - paid, state.box_size)
            await conn.execute("UPDATE Stable SET Ascensions = Ascensions + 1 WHERE UserId = ?", (user_id,))
            await conn.commit()
        return (
            True,
            f"✨ Ascension {state.ascensions + 1}! The box paid out **{paid:,}** coins and your unicorns trotted "
            f"off. You now earn {round(ASCENSION_EARN_BONUS * 100)}% more, but everything costs "
            f"{round((ASCENSION_PRICE_FACTOR - 1) * 100)}% more too.",
        )

    async def top(self, user_ids: set[int], limit: int = 10) -> list[tuple[int, float, int]]:
        """The stables earning most per day among `user_ids`, with their ascension counts."""
        settings = await self.settings()
        async with self.db._get_connection() as conn:
            cursor = await conn.execute("SELECT UserId, Breed, Level, Shiny FROM StableUnicorn")
            unicorns = await cursor.fetchall()
            cursor = await conn.execute("SELECT UserId, Breed FROM StableDiscovery WHERE Shiny = 0")
            discovered: dict[int, set[str]] = {}
            for user_id, breed in await cursor.fetchall():
                if breed in BREEDS:
                    discovered.setdefault(user_id, set()).add(breed)
            cursor = await conn.execute("SELECT UserId, Ascensions FROM Stable")
            ascensions: dict[int, int] = {}
            for user_id, count in await cursor.fetchall():
                ascensions[user_id] = int(count)

        members_unicorns: dict[int, list[Unicorn]] = {}
        for user_id, breed, level, shiny in unicorns:
            if user_id in user_ids and breed in BREEDS:
                members_unicorns.setdefault(user_id, []).append(Unicorn(0, breed, level, None, bool(shiny)))
        totals: dict[int, float] = {}
        for user_id, herd in members_unicorns.items():
            mods = modifiers(herd, discovered.get(user_id, set()), ascensions.get(user_id, 0))
            totals[user_id] = daily_rate(herd, settings["earn_rate"], mods)
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
        return [(user_id, total, ascensions.get(user_id, 0)) for user_id, total in ranked]
