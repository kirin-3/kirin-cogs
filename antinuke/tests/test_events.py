"""Unit tests for the EventHandlers class."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from redbot.core import Config
from redbot.core.bot import Red

from antinuke.actions import QuarantineActions
from antinuke.audit import AuditLogHelper
from antinuke.events import EventHandlers
from antinuke.utils import ActionCache


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    guild_group = config.guild.return_value
    guild_group.enabled = AsyncMock(return_value=True)
    guild_group.trusted_users = AsyncMock(return_value=[])
    guild_group.trusted_roles = AsyncMock(return_value=[])
    guild_group.monitor = AsyncMock(return_value={})
    return config


@pytest.fixture
def event_handlers(config_mock: MagicMock) -> EventHandlers:
    bot = MagicMock(spec=Red)
    action_cache = MagicMock(spec=ActionCache)
    audit_helper = MagicMock(spec=AuditLogHelper)
    quarantine_actions = MagicMock(spec=QuarantineActions)
    return EventHandlers(
        bot, config_mock, action_cache, audit_helper, quarantine_actions
    )


@pytest.mark.asyncio
async def test_on_guild_channel_delete_below_threshold(
    event_handlers: EventHandlers,
) -> None:
    """Below threshold: action is recorded but no investigation is spawned."""
    channel = MagicMock(spec=discord.abc.GuildChannel)
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    channel.guild = guild

    # Return count = 1 (below default threshold of 2)
    cast(MagicMock, event_handlers.action_cache).record_action.return_value = 1

    with patch("antinuke.events.asyncio.create_task") as mock_create_task:
        await event_handlers.on_guild_channel_delete(channel)
        cast(MagicMock, mock_create_task).assert_not_called()

    cast(MagicMock, event_handlers.action_cache).record_action.assert_called_once_with(
        1, 0, "channel_delete", 60
    )


@pytest.mark.asyncio
async def test_on_guild_channel_delete_above_threshold(
    event_handlers: EventHandlers,
) -> None:
    """At threshold: record_action is called and create_task schedules an investigation."""
    channel = MagicMock(spec=discord.abc.GuildChannel)
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    channel.guild = guild

    # Return count = 2 (hits default threshold of 2)
    cast(MagicMock, event_handlers.action_cache).record_action.return_value = 2

    with patch("antinuke.events.asyncio.create_task") as mock_create_task:
        await event_handlers.on_guild_channel_delete(channel)
        # A task must have been scheduled for the investigation coroutine
        cast(MagicMock, mock_create_task).assert_called_once()

    cast(MagicMock, event_handlers.action_cache).record_action.assert_called_once_with(
        1, 0, "channel_delete", 60
    )


@pytest.mark.asyncio
async def test_investigate_channel_deletion_quarantines_culprit(
    event_handlers: EventHandlers,
) -> None:
    """_investigate_channel_deletion calls audit helper then schedules quarantine via create_task."""
    guild = MagicMock(spec=discord.Guild)
    guild.owner_id = 999

    culprit = MagicMock(spec=discord.Member)
    culprit.id = 123
    culprit.roles = []

    audit_mock = cast(MagicMock, event_handlers.audit_helper)
    audit_mock.get_channel_delete_culprit = AsyncMock(return_value=[(culprit, 3)])

    # Culprit is not trusted (owner_id doesn't match, no trusted roles/users)
    guild_group = event_handlers.config.guild.return_value  # type: ignore[union-attr]
    guild_group.trusted_users = AsyncMock(return_value=[])
    guild_group.trusted_roles = AsyncMock(return_value=[])

    config = {"threshold": 2, "timeframe": 60}

    with patch("antinuke.events.asyncio.create_task") as mock_create_task:
        await event_handlers._investigate_channel_deletion(guild, config)

    audit_mock.get_channel_delete_culprit.assert_called_once_with(guild, 60, 2)
    # Quarantine should be scheduled as a task for the untrusted culprit
    cast(MagicMock, mock_create_task).assert_called_once()


@pytest.mark.asyncio
async def test_investigate_channel_deletion_skips_trusted(
    event_handlers: EventHandlers,
) -> None:
    """_investigate_channel_deletion does NOT quarantine a trusted culprit."""
    guild = MagicMock(spec=discord.Guild)
    guild.owner_id = 999

    trusted_culprit = MagicMock(spec=discord.Member)
    trusted_culprit.id = 42
    trusted_culprit.roles = []

    audit_mock = cast(MagicMock, event_handlers.audit_helper)
    audit_mock.get_channel_delete_culprit = AsyncMock(
        return_value=[(trusted_culprit, 3)]
    )
    # Mark culprit as trusted by ID
    guild_group = event_handlers.config.guild.return_value  # type: ignore[union-attr]
    guild_group.trusted_users = AsyncMock(return_value=[42])
    guild_group.trusted_roles = AsyncMock(return_value=[])

    config = {"threshold": 2, "timeframe": 60}

    with patch("antinuke.events.asyncio.create_task") as mock_create_task:
        await event_handlers._investigate_channel_deletion(guild, config)

    cast(MagicMock, mock_create_task).assert_not_called()


@pytest.mark.asyncio
async def test_is_trusted(event_handlers: EventHandlers) -> None:
    guild = MagicMock(spec=discord.Guild)
    guild.owner_id = 1

    # Server owner is always trusted
    owner = MagicMock(spec=discord.Member)
    owner.id = 1
    assert await event_handlers.is_trusted(guild, owner) is True

    # Unknown user with no matching roles/IDs is not trusted
    user2 = MagicMock(spec=discord.Member)
    user2.id = 2
    user2.roles = [MagicMock(id=10)]
    assert await event_handlers.is_trusted(guild, user2) is False

    guild_group = event_handlers.config.guild.return_value  # type: ignore[union-attr]

    # Trusted by explicit user ID
    guild_group.trusted_users = AsyncMock(return_value=[2])
    assert await event_handlers.is_trusted(guild, user2) is True
    guild_group.trusted_users = AsyncMock(return_value=[])

    # Trusted by role ID
    guild_group.trusted_roles = AsyncMock(return_value=[10])
    assert await event_handlers.is_trusted(guild, user2) is True
