"""Tests for the owner-or-designated-user restriction on critical AntiNuke settings."""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from redbot.core import commands

from antinuke.antinuke import AntiNuke, _settings_authority
from antinuke.constants import SETTINGS_AUTHORITY_USER_ID

OWNER_ID = 1000
ADMIN_ID = 2000

RESTRICTED = [
    "antinuke_disable",
    "trust_adduser",
    "trust_removeuser",
    "trust_addrole",
    "trust_removerole",
    "trust_clear",
]


class _Value:
    def __init__(self, store: dict[str, Any], key: str) -> None:
        self.store = store
        self.key = key

    def __call__(self) -> "_Value":
        return self

    def __await__(self):
        async def read() -> Any:
            return self.store[self.key]

        return read().__await__()

    async def __aenter__(self) -> Any:
        return self.store[self.key]

    async def __aexit__(self, *_: object) -> None:
        return None

    async def set(self, value: Any) -> None:
        self.store[self.key] = value


class _GuildConfig:
    def __init__(self, store: dict[str, Any]) -> None:
        self.store = store

    def __getattr__(self, key: str) -> _Value:
        return _Value(self.store, key)


def _cog(store: dict[str, Any]) -> AntiNuke:
    cog = AntiNuke.__new__(AntiNuke)
    cog.config = MagicMock()
    cog.config.guild.return_value = _GuildConfig(store)
    return cog


def _ctx(author_id: int | None, *, guild: bool = True) -> MagicMock:
    ctx = MagicMock()
    if guild:
        ctx.guild = MagicMock(spec=discord.Guild)
        ctx.guild.owner_id = OWNER_ID
    else:
        ctx.guild = None
    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = author_id
    ctx.author.guild_permissions = discord.Permissions(manage_guild=True)
    ctx.send = AsyncMock()
    return ctx


def _store() -> dict[str, Any]:
    return {"enabled": True, "trusted_users": [55], "trusted_roles": [66]}


async def _invoke(cog: AntiNuke, name: str, ctx: MagicMock, *args: Any) -> None:
    """Run a command's own checks then its callback, as a slash or prefix invocation would."""
    command = getattr(AntiNuke, name)
    for check in command.checks:
        if not await check(ctx):
            raise commands.CheckFailure
    await cast(Any, command).callback(cog, ctx, *args)


def _target(name: str) -> tuple[Any, ...]:
    if name in {"trust_adduser", "trust_removeuser"}:
        member = MagicMock(spec=discord.Member)
        member.id = 55 if name == "trust_removeuser" else 77
        member.bot = False
        return (member,)
    if name in {"trust_addrole", "trust_removerole"}:
        role = MagicMock(spec=discord.Role)
        role.id = 66 if name == "trust_removerole" else 88
        role.is_default.return_value = False
        return (role,)
    return ()


@pytest.mark.asyncio
@pytest.mark.parametrize("author_id", [OWNER_ID, SETTINGS_AUTHORITY_USER_ID])
async def test_predicate_allows_owner_and_designated_user(author_id: int) -> None:
    assert await _settings_authority(_ctx(author_id)) is True


@pytest.mark.asyncio
async def test_predicate_refuses_manage_server_admin_with_feedback() -> None:
    with pytest.raises(commands.UserFeedbackCheckFailure) as excinfo:
        await _settings_authority(_ctx(ADMIN_ID))
    assert "server owner" in str(excinfo.value.message)


@pytest.mark.asyncio
async def test_predicate_refuses_outside_guild() -> None:
    with pytest.raises(commands.UserFeedbackCheckFailure):
        await _settings_authority(_ctx(SETTINGS_AUTHORITY_USER_ID, guild=False))


@pytest.mark.asyncio
@pytest.mark.parametrize("name", RESTRICTED)
async def test_admin_is_refused_and_config_unchanged(name: str) -> None:
    store = _store()
    cog = _cog(store)
    ctx = _ctx(ADMIN_ID)

    with pytest.raises(commands.UserFeedbackCheckFailure):
        await _invoke(cog, name, ctx, *_target(name))

    assert store == _store()
    ctx.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", RESTRICTED)
@pytest.mark.parametrize("author_id", [OWNER_ID, SETTINGS_AUTHORITY_USER_ID])
async def test_authorized_user_changes_setting(name: str, author_id: int) -> None:
    store = _store()
    cog = _cog(store)

    await _invoke(cog, name, _ctx(author_id), *_target(name))

    assert store != _store()


@pytest.mark.asyncio
async def test_enable_and_trust_list_keep_existing_access() -> None:
    assert _settings_authority not in AntiNuke.antinuke_enable.checks
    assert _settings_authority not in AntiNuke.trust_list.checks

    store = _store()
    store["enabled"] = False
    ctx = _ctx(ADMIN_ID)
    await _invoke(_cog(store), "antinuke_enable", ctx)
    assert store["enabled"] is True

    ctx.guild.get_member.return_value = None
    ctx.guild.get_role.return_value = None
    await _invoke(_cog(store), "trust_list", ctx)
    ctx.send.assert_awaited()
