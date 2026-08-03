"""Regression tests for deletion without destroying financial audit rows."""

from pathlib import Path

import pytest

from unicornia.db.core import CoreDB


@pytest.mark.asyncio
async def test_delete_anonymizes_financial_audit_rows(tmp_path: Path) -> None:
    db = CoreDB(str(tmp_path / "audit.sqlite3"))
    await db.connect()
    try:
        async with db._get_connection() as connection:
            await connection.execute(
                """CREATE TABLE CurrencyTransactions (
                    Id INTEGER PRIMARY KEY, UserId INTEGER NOT NULL, Type TEXT NOT NULL,
                    Amount INTEGER NOT NULL, Reason TEXT, OtherId INTEGER, Extra TEXT,
                    DateAdded TEXT NOT NULL
                )"""
            )
            await connection.execute(
                """CREATE TABLE EconomyOperations (
                    Id INTEGER PRIMARY KEY, OperationKey TEXT NOT NULL UNIQUE,
                    UserId INTEGER NOT NULL, Result TEXT
                )"""
            )
            await connection.execute(
                "INSERT INTO CurrencyTransactions VALUES (1, 42, 'award', 500, 'username', NULL, 'metadata', 'now')"
            )
            await connection.execute(
                "INSERT INTO EconomyOperations VALUES (7, 'nitro:1:42:event', 42, 'private result')"
            )
            await connection.commit()

        await db.delete_user_data(42)

        async with db._get_connection() as connection:
            transaction = await (
                await connection.execute("SELECT UserId, Amount, Reason, Extra FROM CurrencyTransactions WHERE Id = 1")
            ).fetchone()
            operation = await (
                await connection.execute("SELECT OperationKey, UserId, Result FROM EconomyOperations WHERE Id = 7")
            ).fetchone()
        assert transaction == (0, 500, "[deleted user]", None)
        assert operation is not None
        assert operation[0].startswith("deleted:")
        assert len(operation[0]) == len("deleted:") + 32
        assert operation[1:] == (0, None)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_delete_cleans_all_initialized_user_linked_storage(tmp_path: Path) -> None:
    db = CoreDB(str(tmp_path / "complete-delete.sqlite3"))
    await db.connect()
    await db.initialize()
    try:
        async with db._get_connection() as connection:
            statements = [
                ("INSERT INTO DiscordUser (UserId, Username, CurrencyAmount) VALUES (42, 'private', 500)", ()),
                ("INSERT INTO UserXpStats (UserId, GuildId, Xp) VALUES (42, 1, 10)", ()),
                (
                    "INSERT INTO PlantedCurrency (GuildId, ChannelId, UserId, MessageId, Amount) VALUES (1, 2, 42, 3, 4)",
                    (),
                ),
                ("INSERT INTO XpShopOwnedItem (UserId, ItemType, ItemKey) VALUES (42, 1, 'x')", ()),
                ("INSERT INTO BankUsers (UserId, Balance) VALUES (42, 20)", ()),
                ("INSERT INTO UserBetStats (UserId, Game) VALUES (42, 'mines')", ()),
                ("INSERT INTO Clubs (Id, Name, OwnerId) VALUES (1, 'club', 42)", ()),
                ("INSERT INTO ClubApplicants (ClubId, UserId) VALUES (1, 42)", ()),
                ("INSERT INTO ClubBans (ClubId, UserId) VALUES (1, 42)", ()),
                ("INSERT INTO ClubInvitations (ClubId, UserId) VALUES (1, 42)", ()),
                ("INSERT INTO Rakeback (UserId, RakebackBalance) VALUES (42, 9)", ()),
                ("INSERT INTO TimelyCooldown (UserId, LastClaim) VALUES (42, 'now')", ()),
                ("INSERT INTO ShopEntry (Id, GuildId, `Index`, AuthorId) VALUES (1, 1, 1, 42)", ()),
                ("INSERT INTO UserInventory (UserId, GuildId, ShopEntryId) VALUES (42, 1, 1)", ()),
                ("INSERT INTO Stocks (Symbol, Name, CurrentPrice, PreviousPrice) VALUES ('T', 'Test', 1, 1)", ()),
                ("INSERT INTO StockHoldings (UserId, Symbol, Amount) VALUES (42, 'T', 2)", ()),
                ("INSERT INTO WaifuInfo (WaifuId, ClaimerId, Affinity) VALUES (99, 42, 42)", ()),
                ("INSERT INTO WaifuInfo (WaifuId, ClaimerId) VALUES (42, 99)", ()),
                ("INSERT INTO WaifuUpdates (UserId, OldId, NewId, UpdateType) VALUES (42, 42, 42, 1)", ()),
            ]
            for statement, params in statements:
                await connection.execute(statement, params)
            await connection.commit()

        await db.delete_user_data(42)

        async with db._get_connection() as connection:
            direct_tables = [
                "DiscordUser",
                "UserXpStats",
                "PlantedCurrency",
                "XpShopOwnedItem",
                "BankUsers",
                "UserBetStats",
                "ClubApplicants",
                "ClubBans",
                "ClubInvitations",
                "Rakeback",
                "TimelyCooldown",
                "UserInventory",
                "StockHoldings",
            ]
            for table in direct_tables:
                count = await (await connection.execute(f"SELECT COUNT(*) FROM {table} WHERE UserId = 42")).fetchone()
                assert count == (0,), table

            club = await (await connection.execute("SELECT OwnerId FROM Clubs WHERE Id = 1")).fetchone()
            shop = await (await connection.execute("SELECT AuthorId FROM ShopEntry WHERE Id = 1")).fetchone()
            waifu = await (
                await connection.execute("SELECT ClaimerId, Affinity FROM WaifuInfo WHERE WaifuId = 99")
            ).fetchone()
            deleted_waifu = await (
                await connection.execute("SELECT COUNT(*) FROM WaifuInfo WHERE WaifuId = 42")
            ).fetchone()
            update = await (await connection.execute("SELECT UserId, OldId, NewId FROM WaifuUpdates")).fetchone()
        assert club == (0,)
        assert shop == (0,)
        assert waifu == (None, None)
        assert deleted_waifu == (0,)
        assert update == (0, 0, 0)
    finally:
        await db.close()
