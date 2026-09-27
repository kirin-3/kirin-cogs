"""The member site's read helpers: portfolio, club, waifu status and the stable page, over a real temp database."""

import time
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.market_views import portfolio_totals
from unicornia.systems.stable_system import StableSystem
from unicornia.unicornia import Unicornia

ME, ALICE, BOB = 1, 2, 3
DAY = 86_400


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "member.db"))
    await manager.connect()
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
def cog(db: DatabaseManager) -> Unicornia:
    cog = Unicornia.__new__(Unicornia)
    cog.db = db
    return cog


@pytest.fixture
def stable_cog(db: DatabaseManager) -> Unicornia:
    cog = Unicornia.__new__(Unicornia)
    cog.db = db
    cog._stable_cards = {}
    config = MagicMock()
    config.stable_settings = AsyncMock(return_value={})
    cog.stable_system = StableSystem(db, config)
    return cog


def member(user_id: int = ME) -> Any:
    """A stand-in with the id and display name the stable API reads."""
    return SimpleNamespace(id=user_id, display_name=f"member{user_id}")


async def _run(db: DatabaseManager, *statements: tuple[str, tuple]) -> None:
    async with db._get_connection() as connection:
        for sql, params in statements:
            await connection.execute(sql, params)
        await connection.commit()


def test_portfolio_totals_match_the_command() -> None:
    totals = portfolio_totals([{"amount": 10, "average_cost": 100, "current_price": 120}])

    assert totals == {"value": 1_200, "cost": 1_000, "profit": 200, "profit_pct": 20.0}
    assert portfolio_totals([])["profit_pct"] == 0


# --- portfolio -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_portfolio_with_holdings_and_dividends(cog: Unicornia, db: DatabaseManager) -> None:
    await _run(
        db,
        ("INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice) VALUES ('UNI', 'Unicorn', '🦄', 120)", ()),
        ("INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice) VALUES ('PNY', 'Pony', '🐴', 5)", ()),
        ("INSERT INTO StockHoldings VALUES (?, 'PNY', 2, 10)", (ME,)),
        ("INSERT INTO StockHoldings VALUES (?, 'UNI', 10, 100)", (ME,)),
        ("INSERT INTO StockHoldings VALUES (?, 'UNI', 99, 1)", (ALICE,)),
        ("INSERT INTO DividendPayouts (PeriodEnd, UserId, Symbol, Weight, Amount) VALUES ('2026-01-01', ?, 'UNI', 1, 7)", (ALICE,)),
        *[
            ("INSERT INTO DividendPayouts (PeriodEnd, UserId, Symbol, Weight, Amount) VALUES (?, ?, 'UNI', 0.5, 3)", (f"2026-01-01 {n:02}:00", ME))
            for n in range(60)
        ],
    )  # fmt: skip

    portfolio = await cog.portfolio(ME)

    uni, pny = portfolio["holdings"]
    assert (uni["symbol"], uni["value"], uni["profit"], uni["profit_pct"]) == ("UNI", 1_200, 200, 20.0)
    assert (pny["value"], pny["profit"]) == (10, -10)
    assert portfolio["totals"] == portfolio_totals([uni, pny])
    dividends = portfolio["dividends"]
    assert len(dividends) == 60 and dividends[0]["period_end"] == "2026-01-01 59:00"
    assert {d["amount"] for d in dividends} == {3}


@pytest.mark.asyncio
async def test_portfolio_of_a_member_with_nothing(cog: Unicornia) -> None:
    portfolio = await cog.portfolio(ME)

    assert portfolio["holdings"] == [] and portfolio["dividends"] == []
    assert portfolio["totals"] == {"value": 0, "cost": 0, "profit": 0, "profit_pct": 0}


@pytest.mark.asyncio
async def test_former_shareholder_keeps_their_dividends(cog: Unicornia, db: DatabaseManager) -> None:
    await _run(
        db,
        ("INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice) VALUES ('UNI', 'Unicorn', '🦄', 120)", ()),
        ("INSERT INTO StockHoldings VALUES (?, 'UNI', 0, 100)", (ME,)),
        ("INSERT INTO DividendPayouts (PeriodEnd, UserId, Symbol, Weight, Amount) VALUES ('2026-01-01', ?, 'UNI', 1, 50)", (ME,)),
    )  # fmt: skip

    portfolio = await cog.portfolio(ME)

    assert portfolio["holdings"] == [] and [d["amount"] for d in portfolio["dividends"]] == [50]


# --- club ------------------------------------------------------------------------------------------


async def _club(db: DatabaseManager, name: str, xp: int, owner: int, banner: str = "") -> None:
    await _run(
        db,
        (
            "INSERT INTO Clubs (Name, Description, ImageUrl, BannerUrl, Xp, OwnerId) VALUES (?, 'Shiny', '', ?, ?, ?)",
            (name, banner, xp, owner),
        ),
    )


@pytest.mark.asyncio
async def test_club_member_sees_rank_and_members(cog: Unicornia, db: DatabaseManager) -> None:
    await _club(db, "Big", 900, 99)
    await _club(db, "Sparkles", 500, ALICE, banner="https://i.imgur.com/b.png")
    await _run(
        db,
        *[
            ("INSERT INTO DiscordUser (UserId, Username, TotalXp, ClubId, IsClubAdmin) VALUES (?, ?, ?, 2, ?)", row)
            for row in [(ME, "me", 50, 0), (ALICE, "alice", 10, 0), (BOB, "bob", 5, 1), (4, "dan", 70, 0)]
        ],
    )

    result = await cog.club_for(ME)

    club = result["club"]
    assert result["invitations"] == []
    assert (club["name"], club["xp"], club["rank"], club["owner_id"]) == ("Sparkles", 500, 2, ALICE)
    assert club["banner_url"] == "https://i.imgur.com/b.png"
    assert [(m["user_id"], m["owner"], m["admin"]) for m in club["members"]] == [
        (ALICE, True, False),
        (BOB, False, True),
        (4, False, False),
        (ME, False, False),
    ]


@pytest.mark.asyncio
async def test_member_without_a_club_sees_invitations(cog: Unicornia, db: DatabaseManager) -> None:
    await _club(db, "Sparkles", 500, ALICE)
    await _run(db, ("INSERT INTO ClubInvitations (ClubId, UserId) VALUES (1, ?)", (ME,)))

    invited, nothing = await cog.club_for(ME), await cog.club_for(BOB)

    assert invited == {"club": None, "invitations": [{"name": "Sparkles", "description": "Shiny"}]}
    assert nothing == {"club": None, "invitations": []}


# --- waifu -----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claimed_member_with_gifts(cog: Unicornia, db: DatabaseManager) -> None:
    await _run(
        db,
        ("INSERT INTO WaifuInfo (WaifuId, ClaimerId, Affinity, Price) VALUES (?, ?, ?, 500)", (ME, ALICE, BOB)),
        ("INSERT INTO WaifuInfo (WaifuId, ClaimerId, Affinity, Price) VALUES (?, NULL, ?, 60)", (BOB, ME)),
        *[("INSERT INTO WaifuInfo (WaifuId, ClaimerId, Price) VALUES (?, ?, 70)", (100 + n, ME)) for n in range(14)],
        *[("INSERT INTO WaifuItem (WaifuInfoId, ItemEmoji, Name) VALUES (?, '🌹', 'Rose')", (ME,))] * 3,
        ("INSERT INTO WaifuItem (WaifuInfoId, ItemEmoji, Name) VALUES (?, '🍫', 'Chocolate')", (ME,)),
    )

    status = await cog.waifu_status(ME)

    assert (status["price"], status["claimer_id"], status["affinity_id"]) == (500, ALICE, BOB)
    assert status["affinity_from"] == [BOB]
    assert sorted(w["user_id"] for w in status["waifus"]) == [100 + n for n in range(14)]
    assert status["gifts"] == [
        {"name": "Rose", "emoji": "🌹", "count": 3},
        {"name": "Chocolate", "emoji": "🍫", "count": 1},
    ]


@pytest.mark.asyncio
async def test_never_claimed_member_gets_the_defaults(cog: Unicornia) -> None:
    status = await cog.waifu_status(ME)

    assert status == {
        "price": 50,
        "claimer_id": None,
        "affinity_id": None,
        "affinity_from": [],
        "waifus": [],
        "gifts": [],
    }


# --- the stable page ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stable_page_keeps_undiscovered_breeds_secret(stable_cog: Unicornia, db: DatabaseManager) -> None:
    await _run(
        db,
        ("INSERT INTO StableUnicorn (UserId, Breed, Shiny) VALUES (?, 'cotton', 1)", (ME,)),
        (
            "INSERT INTO StableDiscovery (UserId, Breed, Shiny) VALUES (?, 'cotton', 0), (?, 'cotton', 1), "
            "(?, 'yule', 0)",
            (ME, ME, ME),
        ),
    )

    page = await stable_cog.stable_for(member())

    assert page["found"] == 1 and page["total_breeds"] == 10
    common = page["collection"][0]
    assert common["rarity"] == "Common" and not common["seasonal"]
    cotton, hazel = common["breeds"]
    assert cotton["key"] == "cotton" and cotton["name"] == "Cotton" and cotton["shiny"] is True
    assert cotton["perk"] == "The coin box holds 1 hour more."
    assert hazel == {"key": None, "name": None, "shiny": False, "perk": None}
    seasonal = page["collection"][-1]
    assert seasonal["seasonal"] and [breed["name"] for breed in seasonal["breeds"]] == ["Yule"]
    assert page["perks"] == [{"name": "Cotton", "perk": "The coin box holds 1 hour more."}]
    assert page["box_hours"] == 9  # the bought 8 plus Cotton's perk

    cotton_art = await stable_cog.stable_art_path(ME, "cotton")
    assert cotton_art is not None and cotton_art.name == "cotton.webp"
    assert await stable_cog.stable_art_path(ME, "prism") is None  # undiscovered stays secret
    assert await stable_cog.stable_art_path(ME, "not-a-breed") is None


@pytest.mark.asyncio
async def test_collecting_from_the_site_pays_the_box(stable_cog: Unicornia, db: DatabaseManager) -> None:
    await db.economy.add_currency(ME, 1_000, "award")
    await stable_cog.stable_system.hatch(ME, now=time.time())
    async with db._get_connection() as connection:
        await connection.execute("UPDATE StableUnicorn SET Breed = 'cotton', Shiny = 0")  # a plain known earner
        await connection.commit()

    assert await stable_cog.stable_collect(ME) == 0  # nothing has accrued since the hatch
    async with db._get_connection() as connection:
        await connection.execute("UPDATE Stable SET LastSettle = LastSettle - ?", (DAY,))
        await connection.commit()
    assert await stable_cog.stable_collect(ME) == 3  # a day caps at the 9-hour box (10 a day, Cotton's perk)
    assert await stable_cog.stable_collect(ME) == 0  # and the box is empty again
    assert await db.economy.get_user_currency(ME) == 3


@pytest.mark.asyncio
async def test_the_card_bytes_are_cached_until_the_stable_changes(stable_cog: Unicornia, db: DatabaseManager) -> None:
    me = member()
    first = await stable_cog.stable_card(me)
    assert first[:4] == b"RIFF"  # webp the page can serve
    assert await stable_cog.stable_card(me) is first  # the cached bytes, not a re-render

    await db.economy.add_currency(ME, 1_000, "award")
    await stable_cog.stable_system.hatch(ME, now=time.time())
    second = await stable_cog.stable_card(me)
    assert second is not first and second[:4] == b"RIFF"  # a change re-renders
