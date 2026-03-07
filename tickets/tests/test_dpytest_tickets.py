"""dpytest integration tests for tickets on_member_remove and on_guild_channel_delete."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from tickets.common.utils import prune_invalid_tickets


def make_guild(member: discord.Member | None = None, channels: dict | None = None) -> MagicMock:
    guild = MagicMock()
    guild.id = 1
    guild.name = "Ticket Tests"
    guild.get_member = MagicMock(return_value=member)
    guild.get_channel_or_thread = MagicMock(side_effect=lambda cid: channels.get(cid) if channels else None)
    return guild


def make_config_mock() -> MagicMock:
    config = MagicMock()

    class _OpenedContext:
        async def __aenter__(self) -> dict:
            return self._data

        async def __aexit__(self, *args: object) -> None:
            pass

        def set_data(self, data: dict) -> None:
            self._data = data

    return config


# --- prune_invalid_tickets ---


@pytest.mark.asyncio
async def test_prune_removes_tickets_for_missing_member() -> None:
    """Tickets belonging to members who left the guild should be pruned."""
    guild = make_guild(member=None)  # get_member returns None → member left

    conf = {
        "opened": {"123": {"chan_1": {"logmsg": None}}},
        "log_channel": None,
    }

    config = MagicMock()
    opened_ctx = MagicMock()
    data: dict[str, dict] = {"123": {"chan_1": {"logmsg": None}}}
    opened_ctx.__aenter__ = AsyncMock(return_value=data)
    opened_ctx.__aexit__ = AsyncMock(return_value=False)
    config.guild.return_value.opened = MagicMock(return_value=opened_ctx)

    result = await prune_invalid_tickets(guild, conf, config)  # type: ignore[arg-type]

    assert result is True
    assert "123" not in data  # pruned


@pytest.mark.asyncio
async def test_prune_removes_tickets_for_missing_channel() -> None:
    """Tickets whose channels no longer exist should be pruned."""
    member = MagicMock(spec=discord.Member)

    guild = make_guild(member=member, channels={})  # get_channel_or_thread returns None

    conf = {
        "opened": {"999": {"100": {"logmsg": None}}},
        "log_channel": None,
    }

    config = MagicMock()
    data: dict = {"999": {"100": {"logmsg": None}}}
    opened_ctx = MagicMock()
    opened_ctx.__aenter__ = AsyncMock(return_value=data)
    opened_ctx.__aexit__ = AsyncMock(return_value=False)
    config.guild.return_value.opened = MagicMock(return_value=opened_ctx)

    result = await prune_invalid_tickets(guild, conf, config)  # type: ignore[arg-type]

    assert result is True
    # channel "100" should be removed from data
    if "999" in data:
        assert "100" not in data["999"]


@pytest.mark.asyncio
async def test_prune_no_tickets_returns_false() -> None:
    """Empty opened tickets dict should return False without modification."""
    guild = make_guild()

    conf: dict = {
        "opened": {},
        "log_channel": None,
    }

    config = MagicMock()

    result = await prune_invalid_tickets(guild, conf, config)  # type: ignore[arg-type]

    assert result is False
