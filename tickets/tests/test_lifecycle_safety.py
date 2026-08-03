"""Regression tests for ticket locking and recoverable lifecycle states."""

import asyncio
import copy
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from tickets.common.constants import TicketState
from tickets.common.utils import close_ticket
from tickets.tickets import Tickets


class _ContextValue:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class _GuildGroup:
    def __init__(self, state: dict):
        self.state = state

    def opened(self) -> _ContextValue:
        return _ContextValue(self.state["opened"])

    def all(self) -> _ContextValue:
        return _ContextValue(self.state)


class _Config:
    def __init__(self, guild_id: int, state: dict):
        self.guild_id = guild_id
        self.state = state

    async def all_guilds(self) -> dict[int, dict]:
        return {self.guild_id: copy.deepcopy(self.state)}

    def guild(self, guild) -> _GuildGroup:
        return _GuildGroup(self.state)


@pytest.mark.asyncio
async def test_creation_lock_serializes_one_member_but_not_the_guild() -> None:
    cog = object.__new__(Tickets)
    cog._creation_locks = {}
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    same_entered = asyncio.Event()
    other_entered = asyncio.Event()

    async def first() -> None:
        async with cog._creation_lock(1, 42):
            first_entered.set()
            await release_first.wait()

    async def same_member() -> None:
        await first_entered.wait()
        async with cog._creation_lock(1, 42):
            same_entered.set()

    async def other_member() -> None:
        await first_entered.wait()
        async with cog._creation_lock(1, 99):
            other_entered.set()

    tasks = [asyncio.create_task(coro()) for coro in (first, same_member, other_member)]
    await other_entered.wait()
    assert same_entered.is_set() is False
    release_first.set()
    await asyncio.gather(*tasks)
    assert same_entered.is_set() is True
    assert cog._creation_locks == {}


@pytest.mark.asyncio
async def test_failed_channel_delete_keeps_close_failed_record() -> None:
    ticket = {
        "opened": "2024-01-01T00:00:00+00:00",
        "pfp": None,
        "logmsg": None,
        "state": TicketState.ACTIVE,
    }
    state = {"opened": {"42": {"100": ticket}}, "log_channel": 0, "dm": False}
    config = _Config(1, state)
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.me = MagicMock(spec=discord.Member)
    guild.get_channel.return_value = None
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 100
    channel.name = "ticket-1"
    channel.permissions_for.return_value.manage_channels = True
    channel.delete = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "hidden Discord detail"))
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.display_name = "User"
    member.name = "User"

    await close_ticket(
        MagicMock(),
        member,
        guild,
        channel,
        state,
        "done",
        "Moderator",
        config,  # type: ignore[arg-type]
    )

    assert state["opened"]["42"]["100"]["state"] == TicketState.CLOSE_FAILED


@pytest.mark.asyncio
async def test_reconcile_promotes_pending_placeholder_by_saved_channel_id() -> None:
    pending = {
        "opened": "2024-01-01T00:00:00+00:00",
        "state": TicketState.PENDING,
        "channel_id": None,
        "reconcile_token": "kirin-ticket:1:42:1",
    }
    state = {"opened": {"42": {"pending-1": pending}}}
    config = _Config(1, state)
    guild = MagicMock(spec=discord.Guild)
    guild.name = "Guild"
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 100
    channel.topic = "kirin-ticket:1:42:1"
    guild.get_channel_or_thread.return_value = None
    guild.text_channels = [channel]
    bot = MagicMock()
    bot.get_guild.return_value = guild
    cog = object.__new__(Tickets)
    cog.bot = bot
    cast(Any, cog).config = config

    await cog._reconcile_stale_tickets()

    assert "pending-1" not in state["opened"]["42"]
    assert state["opened"]["42"]["100"]["state"] == TicketState.ACTIVE
    assert "channel_id" not in state["opened"]["42"]["100"]


@pytest.mark.asyncio
async def test_finalize_creation_passes_full_guild_config_to_overview() -> None:
    state = {
        "opened": {"42": {"pending-1": {"state": TicketState.PENDING}}},
        "overview_channel": 123,
        "overview_msg": None,
    }
    cog = object.__new__(Tickets)
    cast(Any, cog).config = _Config(1, state)
    guild = MagicMock(spec=discord.Guild)
    active = {"state": TicketState.ACTIVE, "opened": "2024-01-01T00:00:00+00:00"}

    with patch("tickets.common.functions.update_active_overview", new=AsyncMock(return_value=456)) as overview:
        await cog._finalize_ticket_creation(guild, "42", "pending-1", 100, active)

    overview.assert_awaited_once_with(guild, state)
    assert state["opened"] == {"42": {"100": active}}
    assert state["overview_msg"] == 456


@pytest.mark.asyncio
async def test_slash_close_defers_before_ticket_lookup() -> None:
    cog = object.__new__(Tickets)
    group = MagicMock()
    group.all = AsyncMock(return_value={"opened": {}})
    cog.config = MagicMock()
    cog.config.guild.return_value = group
    ctx = MagicMock()
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.author = MagicMock(spec=discord.Member)
    ctx.channel = MagicMock(spec=discord.TextChannel)
    ctx.channel.id = 100
    ctx.interaction = MagicMock(spec=discord.Interaction)
    ctx.defer = AsyncMock()
    ctx.send = AsyncMock()

    await cog.close_a_ticket.callback(cog, ctx)  # pyright: ignore[reportArgumentType]

    ctx.defer.assert_awaited_once_with(ephemeral=True)
    ctx.send.assert_awaited_once()
