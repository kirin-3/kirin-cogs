"""Tests for the owner-or-designated-user restriction on every AntiNuke command."""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from redbot.core import commands

from antinuke.actions import QuarantineActions
from antinuke.antinuke import AntiNuke, _settings_authority
from antinuke.constants import SETTINGS_AUTHORITY_USER_ID

OWNER_ID = 1000
ADMIN_ID = 2000

RESTRICTED = [
    "antinuke_enable",
    "antinuke_disable",
    "antinuke_logchannel",
    "antinuke_quarantinerole",
    "monitor_enable",
    "monitor_disable",
    "monitor_threshold",
    "monitor_botkick",
    "trust_adduser",
    "trust_removeuser",
    "trust_addrole",
    "trust_removerole",
    "trust_clear",
    "quarantine_restore",
    "quarantine_force",
    "quarantine_clear",
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
    cog.quarantine_actions = QuarantineActions(MagicMock(), cog.config)
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


def _store(name: str = "") -> dict[str, Any]:
    return {
        "enabled": name == "antinuke_disable",
        "log_channel": None,
        "quarantine_role": None,
        "trusted_users": [55],
        "trusted_roles": [66],
        "monitor": {},
        "quarantined_users": {"55": {"roles": [], "state": "completed"}},
    }


async def _invoke(cog: AntiNuke, name: str, ctx: MagicMock, *args: Any) -> None:
    """Run the checks of a command and its parent groups, then its callback, as an invocation would."""
    command = getattr(AntiNuke, name)
    for invoked in [*reversed(command.parents), command]:
        for check in invoked.checks:
            if not await discord.utils.maybe_coroutine(check, ctx):
                raise commands.CheckFailure
    await cast(Any, command).callback(cog, ctx, *args)


def _target(name: str) -> tuple[Any, ...]:
    if name in {"trust_adduser", "trust_removeuser", "quarantine_clear"}:
        member = MagicMock(spec=discord.Member)
        member.id = 77 if name == "trust_adduser" else 55
        member.bot = False
        return (member,)
    if name in {"trust_addrole", "trust_removerole"}:
        role = MagicMock(spec=discord.Role)
        role.id = 66 if name == "trust_removerole" else 88
        role.is_default.return_value = False
        return (role,)
    if name == "antinuke_logchannel":
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 99
        return (channel,)
    if name == "antinuke_quarantinerole":
        role = MagicMock(spec=discord.Role)
        role.id = 98
        return (role,)
    if name in {"monitor_enable", "monitor_disable"}:
        return ("ban",)
    if name == "monitor_threshold":
        return ("ban", 5, 30)
    if name == "monitor_botkick":
        return (False,)
    return ()


def _prepare(cog: AntiNuke, ctx: MagicMock, name: str) -> None:
    """Give commands that act on Discord objects what they need to change state."""
    ctx.guild.me.top_role.__le__.return_value = False
    if name in {"quarantine_restore", "quarantine_force"}:
        cog.quarantine_actions = MagicMock()
        cog.quarantine_actions.restore_user = AsyncMock(return_value=True)
        cog.quarantine_actions.execute_quarantine = AsyncMock(return_value=True)
        cog.action_cache = MagicMock()


def _changed(name: str, store: dict[str, Any], cog: AntiNuke) -> bool:
    if name == "quarantine_restore":
        return cast(AsyncMock, cog.quarantine_actions.restore_user).await_count == 1
    if name == "quarantine_force":
        return cast(AsyncMock, cog.quarantine_actions.execute_quarantine).await_count == 1
    return store != _store(name)


def _args(name: str) -> tuple[Any, ...]:
    if name in {"quarantine_restore", "quarantine_force"}:
        member = MagicMock(spec=discord.Member)
        member.id = 55
        member.top_role = MagicMock()
        return (member,)
    return _target(name)


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
    store = _store(name)
    cog = _cog(store)
    ctx = _ctx(ADMIN_ID)
    _prepare(cog, ctx, name)

    with pytest.raises(commands.UserFeedbackCheckFailure):
        await _invoke(cog, name, ctx, *_args(name))

    assert not _changed(name, store, cog)
    ctx.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", RESTRICTED)
@pytest.mark.parametrize("author_id", [OWNER_ID, SETTINGS_AUTHORITY_USER_ID])
async def test_authorized_user_changes_setting(name: str, author_id: int) -> None:
    store = _store(name)
    cog = _cog(store)
    ctx = _ctx(author_id)
    _prepare(cog, ctx, name)

    await _invoke(cog, name, ctx, *_args(name))

    assert _changed(name, store, cog)


def test_every_antinuke_command_is_behind_the_group_check() -> None:
    assert _settings_authority in AntiNuke.antinuke.checks
    walked = {command.qualified_name for command in AntiNuke.antinuke.walk_commands()}
    assert walked, "the antinuke group should have subcommands"
    for command in AntiNuke.antinuke.walk_commands():
        assert AntiNuke.antinuke in command.parents


@pytest.mark.asyncio
async def test_read_only_commands_are_refused_for_admins() -> None:
    ctx = _ctx(ADMIN_ID)
    with pytest.raises(commands.UserFeedbackCheckFailure):
        await _invoke(_cog(_store()), "trust_list", ctx)
    ctx.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_bots_can_be_trusted() -> None:
    store = _store()
    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = 321
    bot_member.bot = True

    await _invoke(_cog(store), "trust_adduser", _ctx(OWNER_ID), bot_member)

    assert 321 in store["trusted_users"]
