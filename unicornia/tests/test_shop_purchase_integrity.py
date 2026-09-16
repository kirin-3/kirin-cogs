"""Role shop purchases charge at most once and refund failed grants safely."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import pytest_asyncio

from unicornia.database import DatabaseManager
from unicornia.systems.shop_system import ShopSystem

GUILD_ID = 555
ROLE_ID = 9001


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "shop.db"))
    await manager.connect()
    await manager.initialize()
    yield manager
    await manager.close()


def _role() -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = ROLE_ID
    role.name = "Shiny"
    return role


def _guild(role: MagicMock) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.get_role.side_effect = lambda role_id: role if role_id == ROLE_ID else None
    return guild


def _member(guild: MagicMock, user_id: int) -> MagicMock:
    """A member whose cached roles never update, while Discord's (fetched) roles do."""
    server_roles: list[MagicMock] = []
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.guild = guild
    member.roles = []

    async def add_roles(role: MagicMock, **kwargs: object) -> None:
        await asyncio.sleep(0)
        server_roles.append(role)

    member.add_roles = AsyncMock(side_effect=add_roles)
    member.server_roles = server_roles
    return member


def _fetch_members(guild: MagicMock, members: list[MagicMock]) -> None:
    by_id = {member.id: member for member in members}

    async def fetch_member(user_id: int) -> MagicMock:
        await asyncio.sleep(0)
        fetched = MagicMock(spec=discord.Member)
        fetched.id = user_id
        fetched.roles = list(by_id[user_id].server_roles)
        return fetched

    guild.fetch_member = AsyncMock(side_effect=fetch_member)


async def _role_item(system: ShopSystem, price: int) -> int:
    return await system.add_shop_item(GUILD_ID, 1, price, "Shiny role", 1, 0, "Shiny", ROLE_ID)


@pytest.mark.asyncio
async def test_double_click_role_purchase_charges_once(db: DatabaseManager) -> None:
    system = ShopSystem(db, MagicMock(), MagicMock())
    item_id = await _role_item(system, 300)
    guild = _guild(_role())
    member = _member(guild, 1)
    _fetch_members(guild, [member])
    await db.economy.add_currency(member.id, 1_000, "test", "test")

    results = await asyncio.gather(
        system.purchase_item(member, GUILD_ID, item_id),
        system.purchase_item(member, GUILD_ID, item_id),
    )

    assert sorted(success for success, _message, _data in results) == [False, True]
    assert any(message == "You already have this role" for _success, message, _data in results)
    assert await db.economy.get_user_currency(member.id) == 700
    member.add_roles.assert_awaited_once()
    assert system._purchase_locks == {}


@pytest.mark.asyncio
async def test_different_members_purchase_concurrently(db: DatabaseManager) -> None:
    system = ShopSystem(db, MagicMock(), MagicMock())
    item_id = await _role_item(system, 300)
    guild = _guild(_role())
    first = _member(guild, 1)
    second = _member(guild, 2)
    _fetch_members(guild, [first, second])
    for member in (first, second):
        await db.economy.add_currency(member.id, 1_000, "test", "test")

    results = await asyncio.gather(
        system.purchase_item(first, GUILD_ID, item_id),
        system.purchase_item(second, GUILD_ID, item_id),
    )

    assert [success for success, _message, _data in results] == [True, True]
    assert await db.economy.get_user_currency(first.id) == 700
    assert await db.economy.get_user_currency(second.id) == 700


@pytest.mark.asyncio
async def test_fetch_failure_falls_back_to_cached_roles(db: DatabaseManager) -> None:
    system = ShopSystem(db, MagicMock(), MagicMock())
    item_id = await _role_item(system, 300)
    role = _role()
    guild = _guild(role)
    member = _member(guild, 1)
    member.roles = [role]
    guild.fetch_member = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "unavailable"))
    await db.economy.add_currency(member.id, 1_000, "test", "test")

    success, message, _data = await system.purchase_item(member, GUILD_ID, item_id)

    assert (success, message) == (False, "You already have this role")
    assert await db.economy.get_user_currency(member.id) == 1_000


@pytest.mark.asyncio
async def test_failed_grant_of_priced_item_refunds_once(db: DatabaseManager) -> None:
    system = ShopSystem(db, MagicMock(), MagicMock())
    item_id = await _role_item(system, 300)
    guild = _guild(_role())
    member = _member(guild, 1)
    _fetch_members(guild, [member])
    member.add_roles.side_effect = discord.Forbidden(MagicMock(status=403), "missing permissions")
    await db.economy.add_currency(member.id, 1_000, "test", "test")

    success, message, _data = await system.purchase_item(member, GUILD_ID, item_id)

    assert success is False
    assert message == "Failed to assign role. Currency has been refunded."
    assert await db.economy.get_user_currency(member.id) == 1_000
    async with db._get_connection() as connection:
        row = await (
            await connection.execute(
                "SELECT COUNT(*) FROM CurrencyTransactions WHERE UserId = ? AND Type = 'shop_refund'", (member.id,)
            )
        ).fetchone()
    assert row is not None and row[0] == 1


@pytest.mark.asyncio
async def test_failed_grant_of_free_item_does_not_raise(db: DatabaseManager) -> None:
    system = ShopSystem(db, MagicMock(), MagicMock())
    item_id = await _role_item(system, 0)
    guild = _guild(_role())
    member = _member(guild, 1)
    _fetch_members(guild, [member])
    member.add_roles.side_effect = discord.Forbidden(MagicMock(status=403), "missing permissions")

    success, message, _data = await system.purchase_item(member, GUILD_ID, item_id)

    assert success is False
    assert message == "Failed to assign role."
