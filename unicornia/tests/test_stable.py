"""The unicorn stable: its maths, its money moves on a real SQLite database, and the card's buttons on Red."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import AsyncGenerator
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
from unicornia.systems.card_generator import XPCardGenerator
from unicornia.systems.stable_system import (
    BREEDS,
    DEFAULT_SETTINGS,
    MAX_LEVEL,
    MAX_UNICORNS,
    StableState,
    StableSystem,
    Unicorn,
    clean_settings,
    roll_breed,
    settle,
)
from unicornia.unicornia import Unicornia

USER = 7
HOUR = 3600
T0 = 1_000_000.0


def test_the_box_fills_up_to_its_capacity_and_never_loses_coins() -> None:
    assert settle(0, HOUR, 240, 8) == 10
    assert settle(0, 100 * HOUR, 240, 8) == 80  # full after 8 hours
    assert settle(50, -HOUR, 240, 8) == 50  # a clock step back earns nothing
    assert settle(120, HOUR, 240, 8) == 120  # over capacity (a unicorn left): kept, not topped up


def test_hatching_follows_the_rarity_weights() -> None:
    rng = random.Random(1)
    rolls = Counter(BREEDS[roll_breed(rng)].rarity for _ in range(20_000))
    assert set(rolls) == {"common", "uncommon", "rare", "epic", "legendary"}
    assert 0.47 < rolls["common"] / 20_000 < 0.53
    assert 0.005 < rolls["legendary"] / 20_000 < 0.015


def test_prices_grow_and_stop_at_the_limits() -> None:
    unicorns = [Unicorn(i, "cotton", 1, None) for i in range(3)]
    state = StableState(unicorns, 0, 0, 30, dict(DEFAULT_SETTINGS))
    assert state.egg_price == round(1_000 * 1.3**3)
    assert state.level_price(unicorns[0]) == 100
    assert state.level_price(Unicorn(9, "cotton", 3, None)) == round(100 * 1.4**2)
    assert state.level_price(Unicorn(9, "cotton", MAX_LEVEL, None)) is None
    full = StableState([Unicorn(i, "cotton", 1, None) for i in range(MAX_UNICORNS)], 0, 3, 0, dict(DEFAULT_SETTINGS))
    assert full.egg_price is None and full.next_box is None


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
    async with db._get_connection() as conn:
        await conn.execute("UPDATE StableUnicorn SET Breed = 'cotton'")
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
    assert await stable.collect(USER, now=T0 + 100 * HOUR) == 80
    assert await db.economy.get_user_currency(USER) == 90


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
    assert ok and (await stable.state(USER, now=T0)).box_hours == 12
    assert await stable.collect(USER, now=T0 + 100 * HOUR) == 120


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
async def test_deleting_a_users_data_removes_their_stable(db: DatabaseManager, stable: StableSystem) -> None:
    await db.economy.add_currency(USER, 1_000, "award")
    await stable.hatch(USER, now=T0)
    await stable.collect(USER, now=T0)
    await db.delete_user_data(USER)
    async with db._get_connection() as conn:
        for table in ("Stable", "StableUnicorn"):
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
