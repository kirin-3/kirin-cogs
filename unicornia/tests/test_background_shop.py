"""Rank-card backgrounds: the buy/equip rules shared by xpshop and the member site, and the dashboard's read helpers."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.systems.economy_system import EconomySystem
from unicornia.systems.xp_system import XPSystem
from unicornia.unicornia import Unicornia

GUILD_ID = 684
BACKGROUNDS = {
    "default": {"name": "Default Background", "price": 0, "url": "https://x/default.png"},
    "astolfo": {
        "name": "Astolfo",
        "price": 20_000,
        "url": "https://x/Astolfo.gif",
        "preview": "https://x/Astolfo.webp",
        "still": "https://x/Astolfo-still.webp",
    },
    "archer": {"name": "Archer", "price": 20_000, "url": "https://x/archer.gif", "preview": "https://x/archer.webp"},
    "aki": {"name": "Aki", "price": 20_000, "url": "https://x/aki.gif", "hidden": True},
    "retired": {"name": "Retired", "url": "https://x/retired.gif"},
}


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "bg.db"))
    await manager.connect()
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
def cog(db: DatabaseManager, monkeypatch: pytest.MonkeyPatch) -> Unicornia:
    cog = Unicornia.__new__(Unicornia)
    cog.db = db
    cog.xp_system = cast(
        Any, SimpleNamespace(card_generator=SimpleNamespace(get_available_backgrounds=lambda: BACKGROUNDS))
    )
    monkeypatch.setattr(cog, "_check_systems_ready", lambda: True)
    return cog


def _user(user_id: int) -> discord.abc.User:
    return cast(discord.abc.User, SimpleNamespace(id=user_id))


async def _fund(db: DatabaseManager, user_id: int, amount: int) -> None:
    async with db._get_connection() as connection:
        await connection.execute("INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)", (user_id, amount))
        await connection.commit()


async def _count(db: DatabaseManager, sql: str, *params: object) -> int:
    async with db._get_connection() as connection:
        row = await (await connection.execute(sql, params)).fetchone()
        assert row is not None
        return row[0]


# --- 1.1 read-only lookups ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_backgrounds_batch_reads_without_writing(db: DatabaseManager) -> None:
    await db.xp.give_xp_item(1, 1, "astolfo")
    await db.xp.set_active_xp_item(1, 1, "astolfo")
    await db.xp.give_xp_item(2, 1, "archer")  # owned, never equipped
    rows = await _count(db, "SELECT COUNT(*) FROM XpShopOwnedItem")

    assert await db.xp.get_active_backgrounds([1, 2, 3]) == {1: "astolfo", 2: "default", 3: "default"}
    assert await db.xp.get_active_backgrounds([]) == {}
    assert await db.xp.get_owned_backgrounds(2) == {"default", "archer"}
    assert await db.xp.get_owned_backgrounds(3) == {"default"}
    assert await _count(db, "SELECT COUNT(*) FROM XpShopOwnedItem") == rows


# --- 1.1a ranking cache ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_xp_ranking_is_read_once_a_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    system = XPSystem.__new__(XPSystem)
    system._leaderboard_cache = {}
    rows = [(user_id, 1_000 - user_id) for user_id in range(1, 400)]
    system.db = cast(Any, SimpleNamespace(xp=SimpleNamespace(get_all_guild_xp=AsyncMock(return_value=rows))))
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.get_member.side_effect = lambda user_id: SimpleNamespace(bot=user_id == 2) if user_id != 3 else None
    now = [1_000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])

    first = await system.get_filtered_leaderboard(guild)
    now[0] += 59
    second = await system.get_filtered_leaderboard(guild)
    assert system.db.xp.get_all_guild_xp.await_count == 1
    assert first == second
    assert len(first) == 300 and first[:2] == [(1, 999), (4, 996)]  # a bot and a leaver are dropped

    first.clear()  # callers get a copy
    now[0] += 2
    assert len(await system.get_filtered_leaderboard(guild)) == 300
    assert system.db.xp.get_all_guild_xp.await_count == 2


# --- 1.2 buy and equip ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buy_charges_records_logs_and_equips(cog: Unicornia, db: DatabaseManager) -> None:
    await _fund(db, 7, 25_000)

    assert await cog.buy_background(_user(7), "astolfo") == "Astolfo"

    assert await db.economy.get_user_currency(7) == 5_000
    assert await db.xp.get_active_backgrounds([7]) == {7: "astolfo"}
    assert await _count(db, "SELECT COUNT(*) FROM CurrencyTransactions WHERE Type = 'xp_shop_purchase'") == 1


@pytest.mark.parametrize(
    ("key", "wallet", "owned", "message"),
    [
        ("nope", 50_000, False, "Background `nope` not found."),
        ("aki", 50_000, False, "Background `aki` is not available for purchase."),
        ("retired", 50_000, False, "Background `retired` is no longer available for purchase."),
        ("astolfo", 50_000, True, "You already own this background!"),
        ("astolfo", 1_000, False, "Insufficient Slut points! You have 1,000 but need 20,000."),
    ],
)
@pytest.mark.asyncio
async def test_refused_buys_change_nothing(
    cog: Unicornia, db: DatabaseManager, key: str, wallet: int, owned: bool, message: str
) -> None:
    await _fund(db, 7, wallet)
    if owned:
        await db.xp.give_xp_item(7, 1, key)
    items = await _count(db, "SELECT COUNT(*) FROM XpShopOwnedItem")

    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        await cog.buy_background(_user(7), key)

    assert await db.economy.get_user_currency(7) == wallet
    assert await _count(db, "SELECT COUNT(*) FROM XpShopOwnedItem") == items
    assert await _count(db, "SELECT COUNT(*) FROM CurrencyTransactions") == 0


@pytest.mark.asyncio
async def test_use_equips_owned_hidden_and_default_and_refuses_the_rest(cog: Unicornia, db: DatabaseManager) -> None:
    await db.xp.give_xp_item(7, 1, "aki")

    assert await cog.use_background(_user(7), "aki") == "Aki"
    assert await db.xp.get_active_backgrounds([7]) == {7: "aki"}
    with pytest.raises(ValueError, match="You don't own the background `archer`"):
        await cog.use_background(_user(7), "archer")
    assert await db.xp.get_active_backgrounds([7]) == {7: "aki"}
    assert await cog.use_background(_user(7), "default") == "Default Background"
    assert await db.xp.get_active_backgrounds([7]) == {7: "default"}


def test_background_images_fall_back_still_preview_url(cog: Unicornia) -> None:
    assert cog.background_images("astolfo") == ("https://x/Astolfo.webp", "https://x/Astolfo-still.webp")
    assert cog.background_images("archer") == ("https://x/archer.webp", "https://x/archer.webp")
    assert cog.background_images("default") == ("https://x/default.png", "https://x/default.png")
    assert cog.background_images("gone") == ("https://x/default.png", "https://x/default.png")


@pytest.mark.asyncio
async def test_backgrounds_page_lists_hidden_only_when_owned(cog: Unicornia, db: DatabaseManager) -> None:
    listed = {item["key"]: item for item in await cog.backgrounds_for(_user(7))}
    assert set(listed) == {"default", "astolfo", "archer"}
    assert listed["default"]["equipped"] and listed["default"]["owned"]
    assert not listed["astolfo"]["owned"]

    await db.xp.give_xp_item(7, 1, "aki")
    listed = {item["key"]: item for item in await cog.backgrounds_for(_user(7))}
    assert listed["aki"]["owned"] and not listed["aki"]["equipped"]


# --- 1.4 at most one charge -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_buys_charge_once(cog: Unicornia, db: DatabaseManager) -> None:
    await _fund(db, 7, 50_000)

    results = await asyncio.gather(
        cog.buy_background(_user(7), "astolfo"), cog.buy_background(_user(7), "astolfo"), return_exceptions=True
    )

    assert sorted(map(str, results)) == ["Astolfo", "You already own this background!"]
    assert await db.economy.get_user_currency(7) == 30_000
    assert await _count(db, "SELECT COUNT(*) FROM XpShopOwnedItem WHERE ItemKey = 'astolfo'") == 1
    assert await _count(db, "SELECT COUNT(*) FROM CurrencyTransactions") == 1


# --- 1.5 staff read helpers -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_house_stats_numbers(cog: Unicornia, db: DatabaseManager) -> None:
    cog.economy_system = cast(
        Any,
        SimpleNamespace(
            get_gambling_stats=AsyncMock(
                return_value=[
                    ("slots", 0, 0, 0, 50, 1_000, 960, 15, "2026-01-01"),
                    ("dice", 0, 0, 0, 500, 1_000, 900, 0, "2026-01-01"),
                    ("race", 0, 0, 0, 500, 0, 0, 0, None),
                ]
            )
        ),
    )

    house = await cog.house_stats()

    slots, dice, race = house["games"]
    assert slots["rtp"] == pytest.approx(0.975) and slots["low_confidence"] and not slots["off_target"]
    assert dice["deviation"] == pytest.approx(0.9 - house["target"]) and dice["off_target"]
    assert race["rtp"] is None and not race["low_confidence"] and not race["off_target"]
    assert house["pool"]["balance"] == 0 and house["runs"] == []


@pytest.mark.asyncio
async def test_config_snapshot_leaves_out_paths_and_switches(cog: Unicornia) -> None:
    settings = {
        "nadeko_db_path": "/srv/nadeko.db",
        "decay_last_run": 5,
        "xp_enabled": True,
        "timely_amount": 500,
        "generation_channels": [11],
    }
    guild_settings = {"xp_included_channels": [12], "command_whitelist": {"bet": [13, "x"]}, "market_message": 99}
    cog.config = cast(
        Any,
        SimpleNamespace(
            all=AsyncMock(return_value=settings),
            guild=lambda guild: SimpleNamespace(all=AsyncMock(return_value=guild_settings)),
        ),
    )
    guild = cast(discord.Guild, SimpleNamespace(id=GUILD_ID))

    snapshot = await cog.config_snapshot(guild)

    assert snapshot["settings"] == {"timely_amount": 500}
    assert snapshot["generation_channels"] == [11] and snapshot["xp_channels"] == [12]
    assert snapshot["command_whitelist"] == {"bet": [13]}
    assert "99" not in repr(snapshot) and "nadeko" not in repr(snapshot)


@pytest.mark.asyncio
async def test_member_summary_reads_everything_and_writes_nothing(cog: Unicornia, db: DatabaseManager) -> None:
    cog.economy_system = EconomySystem(db, MagicMock(), MagicMock())
    cog.xp_system.get_filtered_leaderboard = AsyncMock(return_value=[(3, 900), (7, 100)])  # type: ignore[attr-defined]
    await _fund(db, 7, 1_500)
    await db.xp.add_xp(7, GUILD_ID, 100)
    await db.economy.log_currency_transaction(7, "timely", 500, "Daily reward")
    guild = cast(discord.Guild, SimpleNamespace(id=GUILD_ID))
    rows = await _count(db, "SELECT COUNT(*) FROM XpShopOwnedItem")

    summary = await cog.member_summary(guild, 7, transactions=5, details=True)
    nobody = await cog.member_summary(guild, 8)

    assert (summary["wallet"], summary["bank"], summary["rank"], summary["xp"].total_xp) == (1_500, 0, 2, 100)
    assert summary["background_name"] == "Default Background" and summary["owned_backgrounds"] == ["default"]
    assert summary["transactions"][0]["reason"] == "Daily reward" and summary["rakeback"] == 0
    assert (nobody["wallet"], nobody["rank"], nobody["transactions"]) == (0, None, [])
    assert "rakeback" not in nobody
    assert await _count(db, "SELECT COUNT(*) FROM XpShopOwnedItem") == rows
