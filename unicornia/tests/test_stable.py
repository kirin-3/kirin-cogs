"""The unicorn stable: its maths, its money moves on a real SQLite database, and the card's buttons on Red."""

from __future__ import annotations

import logging
import random
import time
from collections import Counter
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import pytest_asyncio
import simcord
from redbot.core.bot import Red

import unicornia.systems.currency_systems
import unicornia.systems.xp_system
import unicornia.unicornia
from unicornia.commands.stable import clean_name
from unicornia.database import DatabaseManager
from unicornia.db.core import CoreDB
from unicornia.systems import stable_card
from unicornia.systems.card_generator import XPCardGenerator
from unicornia.systems.stable_system import (
    BREEDS,
    DEFAULT_SETTINGS,
    MAX_LEVEL,
    MAX_UNICORNS,
    REGULAR_BREEDS,
    SEASONAL_BREEDS,
    SEASONS,
    Modifiers,
    StableState,
    StableSystem,
    Unicorn,
    active_season,
    clean_settings,
    collection_bonus,
    daily_rate,
    modifiers,
    roll_hatch,
    settle,
)
from unicornia.unicornia import Unicornia

USER = 7
HOUR = 3600
T0 = 1_000_000.0


def stamp(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> float:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC).timestamp()


def unicorn(breed: str, level: int = 1, shiny: bool = False) -> Unicorn:
    return Unicorn(0, breed, level, None, shiny)


def test_the_box_fills_up_to_its_capacity_and_never_loses_coins() -> None:
    assert settle(0, HOUR, 240, 8) == 10
    assert settle(0, 100 * HOUR, 240, 8) == 80  # full after 8 hours
    assert settle(50, -HOUR, 240, 8) == 50  # a clock step back earns nothing
    assert settle(120, HOUR, 240, 8) == 120  # over capacity (a unicorn left): kept, not topped up


def test_the_seasons_open_and_close_on_the_utc_calendar() -> None:
    for breed in SEASONAL_BREEDS:
        assert active_season(stamp(2026, *SEASONS[breed][0])) == breed  # the first second of the window
    assert active_season(stamp(2026, 10, 15)) == "pumpkin"
    assert active_season(stamp(2026, 11, 2, 23, 59, 59)) == "pumpkin"  # the last second of the window
    assert active_season(stamp(2026, 12, 25)) == "yule"  # Yule crosses the new year...
    assert active_season(stamp(2027, 1, 3)) == "yule"
    assert active_season(stamp(2027, 1, 6, 23, 59, 59)) == "yule"
    assert active_season(stamp(2026, 2, 14)) == "sweetheart"
    assert active_season(stamp(2026, 6, 15)) == "pride"
    # the first second after each window ends
    assert active_season(stamp(2026, 11, 3)) is None
    assert active_season(stamp(2027, 1, 7)) is None
    assert active_season(stamp(2026, 2, 22)) is None
    assert active_season(stamp(2026, 7, 1)) is None
    assert active_season(stamp(2026, 3, 15)) is None  # well outside every season
    assert active_season(stamp(2026, 4, 1)) is None


def test_perks_count_once_per_breed_and_cap_at_25_percent() -> None:
    two_embers = modifiers([unicorn("ember"), unicorn("ember")], set(), 0)
    assert two_embers.earn_multiplier == 1.05  # two Embers still earn 5% more, not 10%
    every_earner = modifiers([unicorn("ember"), unicorn("celestial"), unicorn("prism")], set(), 0)
    assert every_earner.earn_multiplier == 1.25  # 5% + 10% + 10% stops at the cap
    box_perks = modifiers([unicorn("cotton"), unicorn("twilight")], set(), 0)
    assert box_perks.box_bonus_hours == 4
    assert Modifiers().earn_multiplier == 1.0 and Modifiers().box_bonus_hours == 0


def test_the_collection_bonus_pays_for_pairs_and_the_full_set() -> None:
    assert collection_bonus(set()) == 0.0
    assert collection_bonus({"cotton"}) == 0.0
    assert collection_bonus({"cotton", "hazel"}) == 0.02  # completing a rarity
    assert collection_bonus({"cotton", "hazel", "bluebell"}) == 0.02  # an unpaired breed adds nothing
    three_pairs = {"cotton", "hazel", "bluebell", "clover", "rosequartz", "twilight"}
    assert collection_bonus(three_pairs) == 0.06
    nine = REGULAR_BREEDS - {"prism"}
    assert collection_bonus(nine) == 0.08
    assert collection_bonus(REGULAR_BREEDS) == 0.15  # 5 pairs and the full set, at the cap
    assert collection_bonus(REGULAR_BREEDS | SEASONAL_BREEDS) == 0.15  # seasonal breeds add nothing


def test_shiny_perks_multiply() -> None:
    assert Modifiers().shiny_chance == 1 / 200
    assert modifiers([unicorn("bluebell")], set(), 0).shiny_chance == 1 / 100
    both = modifiers([unicorn("bluebell"), unicorn("prism")], set(), 0)
    assert both.shiny_chance == 1 / 50  # Bluebell and Prism quadruple the base chance


def test_bonuses_add_up_before_scaling() -> None:
    # One ascension (+10%), a completed common pair (+2%) and Ember (+5%) over 200 a day of unicorns
    herd = [unicorn("ember", level=8)]
    mods = modifiers(herd, {"cotton", "hazel"}, 1)
    assert mods.earn_multiplier == pytest.approx(1.17)
    assert daily_rate(herd, 1.0, mods) == pytest.approx(234)


def test_prices_rise_with_each_ascension_and_fall_with_perks() -> None:
    three = [unicorn("cotton") for _ in range(3)]
    ascended = StableState(three, 0, 0, dict(DEFAULT_SETTINGS), modifiers(three, set(), 2))
    assert ascended.egg_price == round(1_000 * 1.3**3 * 1.2**2)  # 3,164
    rose = StableState([], 0, 0, dict(DEFAULT_SETTINGS), modifiers([unicorn("rosequartz")], set(), 0))
    assert rose.egg_price == round(1_000 * 0.95)
    hazel = StableState([], 0, 0, dict(DEFAULT_SETTINGS), modifiers([unicorn("hazel")], set(), 3))
    assert hazel.level_price(unicorn("hazel")) == round(100 * 1.2**3 * 0.9)
    full = StableState([unicorn("cotton") for _ in range(MAX_UNICORNS)], 0, 3, dict(DEFAULT_SETTINGS), Modifiers())
    assert full.egg_price is None and full.next_box is None
    assert StableState([], 0, 0, dict(DEFAULT_SETTINGS), Modifiers()).level_price(unicorn("cotton", MAX_LEVEL)) is None


def test_a_shiny_unicorn_earns_ten_percent_more() -> None:
    normal = daily_rate([unicorn("cotton", 10)], 1.0)
    shiny = daily_rate([unicorn("cotton", 10, shiny=True)], 1.0)
    assert normal == 100 and shiny == pytest.approx(110)


def test_the_hatch_roll_follows_the_rarity_weights() -> None:
    rng = random.Random(1)
    rolls = Counter(BREEDS[breed].rarity for breed, _ in (roll_hatch(rng, None, Modifiers()) for _ in range(20_000)))
    assert set(rolls) == {"common", "uncommon", "rare", "epic", "legendary"}
    assert 0.47 < rolls["common"] / 20_000 < 0.53
    assert 0.005 < rolls["legendary"] / 20_000 < 0.015


def test_the_seasonal_share_is_fifteen_percent_in_season_and_zero_out() -> None:
    rng = random.Random(2)
    rolls = [roll_hatch(rng, "yule", Modifiers()) for _ in range(20_000)]
    assert 0.14 < sum(1 for breed, _ in rolls if breed == "yule") / 20_000 < 0.16
    rolls = [roll_hatch(rng, None, Modifiers()) for _ in range(20_000)]
    assert not any(breed in SEASONAL_BREEDS for breed, _ in rolls)


def test_frost_raises_the_rare_and_up_share_one_and_a_half_times() -> None:
    rng = random.Random(3)

    def rare_share(mods: Modifiers) -> float:
        rolls = [roll_hatch(rng, None, mods) for _ in range(40_000)]
        return sum(1 for breed, _ in rolls if BREEDS[breed].rarity in ("rare", "epic", "legendary")) / 40_000

    base = rare_share(Modifiers())
    frost = rare_share(Modifiers(rare_weight_factor=1.5))
    assert 0.20 < base < 0.24
    assert 1.42 < frost / base < 1.58


def test_shinies_hatch_about_one_in_two_hundred() -> None:
    rng = random.Random(4)
    rolls = [roll_hatch(rng, None, Modifiers()) for _ in range(40_000)]
    assert 0.003 < sum(1 for _, shiny in rolls if shiny) / 40_000 < 0.007
    lucky = Modifiers(shiny_chance=modifiers([unicorn("bluebell"), unicorn("prism")], set(), 0).shiny_chance)
    rolls = [roll_hatch(rng, None, lucky) for _ in range(20_000)]
    assert 0.015 < sum(1 for _, shiny in rolls if shiny) / 20_000 < 0.025


def test_settings_fall_back_to_the_defaults() -> None:
    assert clean_settings(None) == DEFAULT_SETTINGS
    settings = clean_settings({"egg_price": 500, "egg_growth": "x", "level_growth": -1, "earn_rate": float("nan")})
    assert settings == {**DEFAULT_SETTINGS, "egg_price": 500.0}


def test_names_must_be_drawable() -> None:
    assert clean_name("  Sir   Sparkles ") == "Sir Sparkles"
    assert clean_name("Ünïcörn-chan!") == "Ünïcörn-chan!"
    assert clean_name("🦄🦄") is None
    assert clean_name("x" * 21) is None
    assert clean_name("   ") is None


def test_the_card_renders_every_breed_shiny_and_not_with_the_new_header() -> None:
    breeds = list(BREEDS)
    for start in range(0, len(breeds), MAX_UNICORNS):
        chunk = breeds[start : start + MAX_UNICORNS]
        herd = [Unicorn(slot, breed, slot % MAX_LEVEL + 1, None, slot % 2 == 0) for slot, breed in enumerate(chunk)]
        state = StableState(
            herd,
            100.0,
            2,
            dict(DEFAULT_SETTINGS),
            modifiers(herd, REGULAR_BREEDS, 2),
            2,
            frozenset(REGULAR_BREEDS),
            frozenset(),
        )
        image = stable_card.render(state, "Tester", "yule")
        assert image.getvalue()[:4] == b"RIFF"  # a webp the card can post


class FixedRandom(random.Random):
    """A Random whose random() always lands on `value`, for forcing rare rolls in tests."""

    def __init__(self, value: float) -> None:
        super().__init__(0)
        self.value = value

    def random(self) -> float:
        return self.value


@pytest.mark.asyncio
async def test_clovers_free_egg_costs_nothing_but_must_be_affordable(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 1_000, "award")
    await stable.hatch(USER, now=T0)
    async with db._get_connection() as conn:
        await conn.execute("UPDATE StableUnicorn SET Breed = 'clover'")
        await conn.commit()

    stable.rng = FixedRandom(0.05)  # the 10% free roll succeeds; the 1-in-200 shiny roll doesn't
    _breed, message = await stable.hatch(USER, now=T0)  # the next egg costs 1,300 and the wallet is empty
    assert "don't have enough" in message
    assert len((await stable.state(USER, now=T0)).unicorns) == 1

    await db.economy.add_currency(USER, 5_000, "award")
    _breed, message = await stable.hatch(USER, now=T0)
    assert "free" in message
    assert await db.economy.get_user_currency(USER) == 5_000  # the wallet is untouched
    history = await db.economy.get_currency_transactions(USER, limit=None)
    assert sum(1 for row in history if "stable_egg" in row) == 1  # only the first, paid egg is in the ledger


@pytest.mark.asyncio
async def test_a_shiny_hatch_is_remembered_in_both_discovery_rows(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 10_000, "award")
    stable.rng = FixedRandom(0.001)  # no Clover to trigger, and the shiny roll (1 in 200) succeeds
    breed, message = await stable.hatch(USER, now=T0)
    assert "shiny" in message
    state = await stable.state(USER, now=T0)
    assert state.unicorns[0].shiny
    assert state.discovered == {breed} and state.shiny_found == {breed}
    async with db._get_connection() as conn:
        rows = await (
            await conn.execute("SELECT Breed, Shiny FROM StableDiscovery WHERE UserId = ?", (USER,))
        ).fetchall()
    assert rows == [(breed, 0), (breed, 1)]


@pytest.mark.asyncio
async def test_discoveries_survive_releases(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 1_000, "award")
    breed, _ = await stable.hatch(USER, now=T0)
    unicorn = (await stable.state(USER, now=T0)).unicorns[0]
    assert await stable.release(USER, unicorn.id, now=T0)
    state = await stable.state(USER, now=T0)
    assert state.unicorns == [] and state.discovered == {breed}


@pytest.mark.asyncio
async def test_ascending_pays_the_box_empties_the_stable_and_counts_up(
    db: DatabaseManager, stable: StableSystem
) -> None:
    await db.economy.add_currency(USER, 1_000, "award")
    await stable.hatch(USER, now=T0)
    await only_common(db)
    async with db._get_connection() as conn:
        await conn.execute("UPDATE StableUnicorn SET Level = 10")
        for _ in range(MAX_UNICORNS - 1):
            await conn.execute("INSERT INTO StableUnicorn (UserId, Breed, Level) VALUES (?, 'hazel', 10)", (USER,))
        await conn.commit()

    ok, message = await stable.ascend(USER, now=T0 + HOUR)
    assert ok and "Ascension 1" in message
    assert await db.economy.get_user_currency(USER) == 1_000  # the hour the box earned, paid as stable_ascend
    history = await db.economy.get_currency_transactions(USER, limit=None)
    assert sum(1 for row in history if "stable_ascend" in row) == 1

    state = await stable.state(USER, now=T0 + HOUR)
    assert state.unicorns == [] and state.ascensions == 1
    assert state.discovered and state.box_size == 0  # the collection and the box size are kept
    assert state.egg_price == round(1_000 * 1.2)  # prices rise with the ascension


@pytest.mark.asyncio
async def test_ascending_needs_ten_level_ten_unicorns(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 1_000, "award")
    await stable.hatch(USER, now=T0)
    ok, message = await stable.ascend(USER, now=T0)
    assert not ok and "You need 10 unicorns" in message

    async with db._get_connection() as conn:
        for _ in range(MAX_UNICORNS - 1):
            await conn.execute("INSERT INTO StableUnicorn (UserId, Breed) VALUES (?, 'cotton')", (USER,))
        await conn.commit()
    ok, message = await stable.ascend(USER, now=T0)
    assert not ok and "Every unicorn must be level 10" in message
    state = await stable.state(USER, now=T0)
    assert len(state.unicorns) == MAX_UNICORNS and state.ascensions == 0


@pytest.mark.asyncio
async def test_seasonal_eggs_hatch_only_in_their_window(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 1_000_000, "award")
    stable.rng = FixedRandom(0.10)  # below the 15% seasonal roll, above the shiny roll

    breed, message = await stable.hatch(USER, now=stamp(2026, 12, 15))
    assert breed == "yule" and "Yule" in message
    assert "yule" in (await stable.state(USER, now=stamp(2026, 12, 15))).discovered

    for out_of_season in (stamp(2027, 1, 7), stamp(2026, 7, 15)):
        breed, _ = await stable.hatch(USER, now=out_of_season)
        assert breed in REGULAR_BREEDS
    state = await stable.state(USER, now=stamp(2026, 7, 15))
    assert "yule" in state.discovered  # the season's discoveries and unicorns stay after the window
    assert not state.discovered & (SEASONAL_BREEDS - {"yule"})


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "stable.db"))
    await manager.connect()
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()


@pytest.fixture
def stable(db: DatabaseManager) -> StableSystem:
    config = MagicMock()
    # 24 times the earnings: a common level-1 unicorn earns 240 a day, 10 an hour, and fills the 8-hour box at 80
    config.stable_settings = AsyncMock(return_value={"earn_rate": 24})
    return StableSystem(db, config, rng=random.Random(0))


async def only_common(db: DatabaseManager) -> None:
    """Force every unicorn to a plain Cotton: a known 10-an-hour earner whose perk adds an hour of box."""
    async with db._get_connection() as conn:
        await conn.execute("UPDATE StableUnicorn SET Breed = 'cotton', Shiny = 0")
        await conn.commit()


@pytest.mark.asyncio
async def test_an_egg_costs_coins_and_hatches_a_unicorn(db: DatabaseManager, stable: StableSystem) -> None:
    breed, message = await stable.hatch(USER, now=T0)
    assert breed is None and "1,000" in message
    assert (await stable.state(USER, now=T0)).unicorns == []

    await db.economy.add_currency(USER, 2_500, "award")
    breed, message = await stable.hatch(USER, now=T0)
    assert breed in BREEDS and BREEDS[breed].name in message
    assert await db.economy.get_user_currency(USER) == 1_500
    _breed, _ = await stable.hatch(USER, now=T0)
    assert await db.economy.get_user_currency(USER) == 1_500 - 1_300  # the second egg costs 1.3 times as much
    assert len((await stable.state(USER, now=T0)).unicorns) == 2
    history = await db.economy.get_currency_transactions(USER, limit=None)
    assert sum(1 for row in history if "stable_egg" in row) == 2


@pytest.mark.asyncio
async def test_collecting_pays_what_the_box_earned_up_to_its_size(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 1_000, "award")
    await stable.hatch(USER, now=T0)
    await only_common(db)

    assert await stable.collect(USER, now=T0 + HOUR) == 10
    assert await stable.collect(USER, now=T0 + HOUR) == 0
    assert await stable.collect(USER, now=T0 + 100 * HOUR) == 90  # Cotton's perk makes the box hold 9 hours
    assert await db.economy.get_user_currency(USER) == 100


@pytest.mark.asyncio
async def test_changes_settle_first_so_new_earnings_start_from_then(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 1_100, "award")
    await stable.hatch(USER, now=T0)
    await only_common(db)
    unicorn = (await stable.state(USER, now=T0)).unicorns[0]

    ok, _ = await stable.upgrade(USER, unicorn.id, now=T0 + HOUR)  # 10 earned at level 1
    assert ok and await db.economy.get_user_currency(USER) == 0
    assert await stable.collect(USER, now=T0 + 2 * HOUR) == 10 + 20  # then an hour at level 2

    ok, message = await stable.upgrade(USER, unicorn.id, now=T0 + 2 * HOUR)
    assert not ok and "don't have enough" in message


@pytest.mark.asyncio
async def test_a_bigger_box_holds_more(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 6_000, "award")
    await stable.hatch(USER, now=T0)
    await only_common(db)
    ok, _ = await stable.upgrade_box(USER, now=T0)
    assert ok and (await stable.state(USER, now=T0)).box_hours == 13  # 12 bought, 1 from Cotton's perk
    assert await stable.collect(USER, now=T0 + 100 * HOUR) == 130


@pytest.mark.asyncio
async def test_releasing_keeps_the_earnings_and_frees_the_stall(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 1_000, "award")
    await stable.hatch(USER, now=T0)
    await only_common(db)
    unicorn = (await stable.state(USER, now=T0)).unicorns[0]

    assert await stable.release(USER, unicorn.id, now=T0 + HOUR)
    assert not await stable.release(USER, unicorn.id, now=T0 + HOUR)
    state = await stable.state(USER, now=T0 + 5 * HOUR)
    assert state.unicorns == [] and state.egg_price == 1_000
    assert await stable.collect(USER, now=T0 + 5 * HOUR) == 10


@pytest.mark.asyncio
async def test_the_schema_expansion_upgrades_an_old_stable_database(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db = CoreDB(str(tmp_path / "old-stable.db"))
    await db.connect()
    try:
        # A database from before shinies, ascensions and the collection
        async with db._get_connection() as conn:
            await conn.execute(
                """CREATE TABLE Stable (
                    UserId INTEGER PRIMARY KEY, Box REAL NOT NULL DEFAULT 0,
                    LastSettle REAL NOT NULL, BoxSize INTEGER NOT NULL DEFAULT 0
                )"""
            )
            await conn.execute(
                """CREATE TABLE StableUnicorn (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT, UserId INTEGER NOT NULL, Breed TEXT NOT NULL,
                    Level INTEGER NOT NULL DEFAULT 1, Name TEXT, DateAdded TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            await conn.execute(
                "INSERT INTO StableUnicorn (UserId, Breed) VALUES (7, 'cotton'), (7, 'cotton'), (8, 'prism')"
            )
            await conn.commit()

        with caplog.at_level(logging.ERROR, logger="red.kirin_cogs.unicornia.database"):
            await db.initialize()
            await db.initialize()

        async with db._get_connection() as conn:
            unicorn_columns = await (await conn.execute("PRAGMA table_info(StableUnicorn)")).fetchall()
            stable_columns = await (await conn.execute("PRAGMA table_info(Stable)")).fetchall()
            discovered = await (
                await conn.execute("SELECT UserId, Breed, Shiny FROM StableDiscovery ORDER BY UserId, Breed")
            ).fetchall()
        assert "Shiny" in {row[1] for row in unicorn_columns}
        assert "Ascensions" in {row[1] for row in stable_columns}
        assert discovered == [(7, "cotton", 0), (8, "prism", 0)]  # the duplicate Cotton counts once
        assert not [record for record in caplog.records if "updating database schema" in record.message]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_deleting_a_users_data_removes_their_stable(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 1_000, "award")
    await stable.hatch(USER, now=T0)
    await stable.collect(USER, now=T0)
    async with db._get_connection() as conn:
        await conn.execute(
            "INSERT INTO StableDiscovery (UserId, Breed) VALUES (?, 'cotton'), (?, 'yule')", (USER, USER)
        )
        await conn.commit()
    await db.delete_user_data(USER)
    async with db._get_connection() as conn:
        for table in ("Stable", "StableUnicorn", "StableDiscovery"):
            cursor = await conn.execute(f"SELECT COUNT(*) FROM {table}")
            assert await cursor.fetchone() == (0,)


_PATH_MODULES = (unicornia.unicornia, unicornia.systems.xp_system, unicornia.systems.currency_systems)


@pytest.fixture
def red_cogs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    data_dir = tmp_path / "unicornia-data"
    for module in _PATH_MODULES:
        monkeypatch.setattr(module, "__file__", str(data_dir / (module.__name__.rsplit(".", 1)[-1] + ".py")))
    monkeypatch.setattr(XPCardGenerator, "_ensure_bundled_fonts", AsyncMock())
    return ["unicornia"]


def release_menu(card: discord.Message) -> str:
    """The custom ID of the card's Release menu, which the view generates."""
    for row in card.components:
        for item in getattr(row, "children", []):
            if isinstance(item, discord.SelectMenu) and item.placeholder == "Release a unicorn…":
                assert item.custom_id is not None
                return item.custom_id
    raise AssertionError("no Release menu on the card")


def ascend_button(card: discord.Message) -> discord.Button:
    for row in card.components:
        for item in getattr(row, "children", []):
            if isinstance(item, discord.Button) and item.label == "Ascend":
                return item
    raise AssertionError("no Ascend button on the card")


@pytest.mark.asyncio
async def test_the_stable_card_and_its_buttons(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Unicornia")
    assert isinstance(cog, Unicornia)
    guild = red_env.create_guild()
    owner = guild.add_member(red_env.create_user("owner"))
    visitor = guild.add_member(red_env.create_user("visitor"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await cog.db.economy.add_currency(owner.id, 1_000, "award")

    await owner.send(channel, "!stable")
    card = channel.last_message
    assert card is not None and card.attachments[0].filename == "stable.webp"

    refused = await visitor.click(card, label="Hatch egg · 1,000")
    assert refused.response is not None and refused.response.ephemeral

    await owner.click(card, label="Hatch egg · 1,000")
    card = channel.last_message
    assert card is not None and "The egg hatched into" in card.content
    assert len((await cog.stable_system.state(owner.id)).unicorns) == 1
    assert await cog.db.economy.get_user_currency(owner.id) == 0

    # Releasing from the card asks privately first; Keep changes nothing
    (unicorn,) = (await cog.stable_system.state(owner.id)).unicorns
    asked = await owner.select(card, [str(unicorn.id)], custom_id=release_menu(card))
    assert asked.response is not None and asked.response.ephemeral and "Release **#1" in asked.response.content
    await owner.click(asked.response.message, label="Keep")
    assert len((await cog.stable_system.state(owner.id)).unicorns) == 1

    asked = await owner.select(card, [str(unicorn.id)], custom_id=release_menu(card))
    assert asked.response is not None
    await owner.click(asked.response.message, label="Release")
    assert (await cog.stable_system.state(owner.id)).unicorns == []
    card = channel.last_message
    assert card is not None and "trotted off into the sunset" in card.content

    await visitor.send(channel, f"!stable {owner.id}")  # someone else's stable: the card, no buttons
    shown = channel.last_message
    assert shown is not None and shown.attachments and not shown.components
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_the_ascend_button_asks_first_and_empties_the_stable(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Unicornia")
    assert isinstance(cog, Unicornia)
    guild = red_env.create_guild()
    owner = guild.add_member(red_env.create_user("ascender"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await owner.send(channel, "!stable")
    card = channel.last_message
    assert card is not None and ascend_button(card).disabled  # a small stable can't ascend

    async with cog.db._get_connection() as conn:
        for _ in range(MAX_UNICORNS):
            await conn.execute("INSERT INTO StableUnicorn (UserId, Breed, Level) VALUES (?, 'cotton', 10)", (owner.id,))
        await conn.execute(
            "INSERT INTO Stable (UserId, Box, LastSettle, BoxSize, Ascensions) VALUES (?, 900, ?, 1, 0)",
            (owner.id, time.time()),
        )
        await conn.commit()

    await owner.send(channel, "!stable")
    card = channel.last_message
    assert card is not None and not ascend_button(card).disabled
    asked = await owner.click(card, label="Ascend")
    assert asked.response is not None and asked.response.ephemeral and "Ascend?" in asked.response.content
    await owner.click(asked.response.message, label="Ascend")

    state = await cog.stable_system.state(owner.id)
    assert state.unicorns == [] and state.ascensions == 1
    assert await cog.db.economy.get_user_currency(owner.id) == 900  # the box paid out
    settled = channel.last_message
    assert settled is not None and "Ascension 1" in settled.content
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_the_collection_command_keeps_undiscovered_breeds_secret(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Unicornia")
    assert isinstance(cog, Unicornia)
    guild = red_env.create_guild()
    owner = guild.add_member(red_env.create_user("collector"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    async with cog.db._get_connection() as conn:
        await conn.execute("INSERT INTO StableUnicorn (UserId, Breed, Shiny) VALUES (?, 'cotton', 1)", (owner.id,))
        await conn.execute(
            "INSERT INTO StableDiscovery (UserId, Breed, Shiny) VALUES (?, 'cotton', 0), (?, 'cotton', 1), "
            "(?, 'yule', 0)",
            (owner.id, owner.id, owner.id),
        )
        await conn.commit()

    await owner.send(channel, "!stable collection")
    message = channel.last_message
    assert message is not None and message.embeds
    embed = message.embeds[0]
    text = (embed.description or "") + "\n" + "\n".join(f"{field.name}\n{field.value}" for field in embed.fields)
    assert "Cotton" in text and "box holds 1 hour more" in text  # discovered: name and perk
    assert "Yule" in text  # seasonal finds have their own field
    assert text.count("???") == 9  # every regular breed but Cotton stays a question mark
    for secret in ("Hazel", "Bluebell", "Prism", "Celestial"):
        assert secret not in text
    assert "Level-ups cost" not in text  # an undiscovered breed's perk stays secret with its name
    assert "✨ Shiny found: Cotton" in text
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_the_top_command_shows_ascensions(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Unicornia")
    assert isinstance(cog, Unicornia)
    guild = red_env.create_guild()
    owner = guild.add_member(red_env.create_user("topper"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    async with cog.db._get_connection() as conn:
        await conn.execute("INSERT INTO StableUnicorn (UserId, Breed, Level) VALUES (?, 'prism', 10)", (owner.id,))
        await conn.execute(
            "INSERT INTO Stable (UserId, Box, LastSettle, BoxSize, Ascensions) VALUES (?, 0, ?, 0, 2)",
            (owner.id, time.time()),
        )
        await conn.commit()

    await owner.send(channel, "!stable top")
    message = channel.last_message
    assert message is not None and message.embeds
    assert "★ 2" in (message.embeds[0].description or "")
    simcord.assert_no_errors(red_env)
