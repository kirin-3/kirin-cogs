"""Unit tests for audit-log-driven detection in EventHandlers."""

import asyncio
import copy
from collections.abc import Coroutine, Iterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from redbot.core import Config
from redbot.core.bot import Red

from antinuke.actions import QuarantineActions
from antinuke.constants import DEFAULT_GUILD
from antinuke.events import AUDIT_ACTION_TYPES, EventHandlers
from antinuke.utils import ActionCache

GUILD_ID = 1
OWNER_ID = 10
BOT_SELF_ID = 900
ROGUE_ID = 20
OTHER_ID = 30


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    guild_group = config.guild.return_value
    guild_group.enabled = AsyncMock(return_value=True)
    guild_group.trusted_users = AsyncMock(return_value=[])
    guild_group.trusted_roles = AsyncMock(return_value=[])
    guild_group.monitor = AsyncMock(return_value=copy.deepcopy(DEFAULT_GUILD["monitor"]))
    return config


@pytest.fixture
def event_handlers(config_mock: MagicMock) -> EventHandlers:
    handlers = EventHandlers(MagicMock(spec=Red), config_mock, ActionCache(), MagicMock(spec=QuarantineActions))
    return handlers


@pytest.fixture
def scheduled(event_handlers: EventHandlers) -> Iterator[list[Coroutine[Any, Any, Any]]]:
    tasks: list[Coroutine[Any, Any, Any]] = []
    event_handlers._create_task = tasks.append  # type: ignore[method-assign]
    yield tasks
    for coroutine in tasks:
        coroutine.close()


def _member(user_id: int, *, bot: bool = False) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.bot = bot
    member.roles = []
    return member


@pytest.fixture
def guild() -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.owner_id = OWNER_ID
    members = {
        OWNER_ID: _member(OWNER_ID),
        BOT_SELF_ID: _member(BOT_SELF_ID, bot=True),
        ROGUE_ID: _member(ROGUE_ID),
        OTHER_ID: _member(OTHER_ID),
    }
    guild.me = members[BOT_SELF_ID]
    guild.get_member.side_effect = members.get
    guild.members_by_id = members
    return guild


def _entry(
    guild: MagicMock,
    action: discord.AuditLogAction,
    user_id: int | None = ROGUE_ID,
    *,
    before: object = None,
    after: object = None,
    target: object = None,
) -> MagicMock:
    entry = MagicMock(spec=discord.AuditLogEntry)
    entry.guild = guild
    entry.action = action
    entry.user_id = user_id
    entry.before = before if before is not None else discord.AuditLogDiff()
    entry.after = after if after is not None else discord.AuditLogDiff()
    entry.target = target
    return entry


def _diff(**attrs: Any) -> discord.AuditLogDiff:
    diff = discord.AuditLogDiff()
    for key, value in attrs.items():
        setattr(diff, key, value)
    return diff


def _quarantined(handlers: EventHandlers) -> list[tuple[Any, ...]]:
    return [c.args for c in cast(MagicMock, handlers.quarantine_actions.execute_quarantine).call_args_list]


# --- classification ---


@pytest.mark.parametrize(("action", "action_type"), list(AUDIT_ACTION_TYPES.items()))
def test_classify_direct_actions(guild: MagicMock, action: discord.AuditLogAction, action_type: str) -> None:
    assert EventHandlers.classify(_entry(guild, action), {}) == action_type


def test_classify_role_update_needs_a_new_dangerous_permission(guild: MagicMock) -> None:
    granted = _entry(
        guild,
        discord.AuditLogAction.role_update,
        before=_diff(permissions=discord.Permissions.none()),
        after=_diff(permissions=discord.Permissions(ban_members=True)),
    )
    harmless = _entry(
        guild,
        discord.AuditLogAction.role_update,
        before=_diff(permissions=discord.Permissions.none()),
        after=_diff(permissions=discord.Permissions(send_messages=True)),
    )
    renamed = _entry(guild, discord.AuditLogAction.role_update, after=_diff(name="new"))

    assert EventHandlers.classify(granted, {}) == "dangerous_permission_add"
    assert EventHandlers.classify(harmless, {}) is None
    assert EventHandlers.classify(renamed, {}) is None


def test_classify_role_update_respects_configured_permissions(guild: MagicMock) -> None:
    entry = _entry(
        guild,
        discord.AuditLogAction.role_update,
        before=_diff(permissions=discord.Permissions.none()),
        after=_diff(permissions=discord.Permissions(ban_members=True)),
    )
    monitor = {"dangerous_permission_add": {"permissions": ["administrator"]}}

    assert EventHandlers.classify(entry, monitor) is None


def test_classify_guild_update_only_for_vanity(guild: MagicMock) -> None:
    vanity = _entry(guild, discord.AuditLogAction.guild_update, after=_diff(vanity_url_code="stolen"))
    renamed = _entry(guild, discord.AuditLogAction.guild_update, after=_diff(name="new"))

    assert EventHandlers.classify(vanity, {}) == "vanity_change"
    assert EventHandlers.classify(renamed, {}) is None
    assert EventHandlers.classify(_entry(guild, discord.AuditLogAction.message_delete), {}) is None


# --- thresholds ---


@pytest.mark.asyncio
async def test_actions_below_threshold_do_nothing(
    event_handlers: EventHandlers, guild: MagicMock, scheduled: list
) -> None:
    # channel_delete defaults to 2 within 60s
    await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.channel_delete))

    assert scheduled == []


@pytest.mark.asyncio
async def test_threshold_quarantines_the_actor(
    event_handlers: EventHandlers, guild: MagicMock, scheduled: list
) -> None:
    for _ in range(2):
        await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.channel_delete))

    assert _quarantined(event_handlers) == [
        (guild, guild.members_by_id[ROGUE_ID], "channel_delete", event_handlers.action_cache)
    ]


@pytest.mark.asyncio
async def test_actions_are_counted_per_actor(event_handlers: EventHandlers, guild: MagicMock, scheduled: list) -> None:
    await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.channel_delete, ROGUE_ID))
    await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.channel_delete, OTHER_ID))

    assert scheduled == []


@pytest.mark.asyncio
async def test_prune_is_instant(event_handlers: EventHandlers, guild: MagicMock, scheduled: list) -> None:
    await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.member_prune))

    assert _quarantined(event_handlers) == [
        (guild, guild.members_by_id[ROGUE_ID], "guild_prune", event_handlers.action_cache)
    ]


@pytest.mark.asyncio
async def test_dangerous_permission_grant_is_instant(
    event_handlers: EventHandlers, guild: MagicMock, scheduled: list
) -> None:
    entry = _entry(
        guild,
        discord.AuditLogAction.role_update,
        before=_diff(permissions=discord.Permissions.none()),
        after=_diff(permissions=discord.Permissions(administrator=True)),
    )
    await event_handlers.on_audit_log_entry_create(entry)

    assert [args[2] for args in _quarantined(event_handlers)] == ["dangerous_permission_add"]


# --- who is exempt ---


@pytest.mark.asyncio
async def test_trusted_actor_is_skipped(
    event_handlers: EventHandlers, config_mock: MagicMock, guild: MagicMock, scheduled: list
) -> None:
    config_mock.guild.return_value.trusted_users = AsyncMock(return_value=[ROGUE_ID])

    await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.member_prune))

    assert scheduled == []


@pytest.mark.asyncio
async def test_owner_is_skipped(event_handlers: EventHandlers, guild: MagicMock, scheduled: list) -> None:
    await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.member_prune, OWNER_ID))

    assert scheduled == []


@pytest.mark.asyncio
async def test_this_bot_is_never_a_culprit(event_handlers: EventHandlers, guild: MagicMock, scheduled: list) -> None:
    """The bot's own bans (e.g. honeypot enforcement) must never lead to acting against the bot."""
    for _ in range(5):
        await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.ban, BOT_SELF_ID))

    assert scheduled == []


@pytest.mark.asyncio
async def test_disabled_monitor_or_cog_does_nothing(
    event_handlers: EventHandlers, config_mock: MagicMock, guild: MagicMock, scheduled: list
) -> None:
    monitor = copy.deepcopy(DEFAULT_GUILD["monitor"])
    monitor["guild_prune"]["enabled"] = False
    config_mock.guild.return_value.monitor = AsyncMock(return_value=monitor)
    await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.member_prune))

    config_mock.guild.return_value.monitor = AsyncMock(return_value=copy.deepcopy(DEFAULT_GUILD["monitor"]))
    config_mock.guild.return_value.enabled = AsyncMock(return_value=False)
    await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.member_prune))

    assert scheduled == []


# --- bots as culprits ---


@pytest.mark.asyncio
async def test_rogue_bot_is_removed_not_quarantined(
    event_handlers: EventHandlers, guild: MagicMock, scheduled: list
) -> None:
    rogue_bot = _member(555, bot=True)
    guild.get_member.side_effect = {**guild.members_by_id, 555: rogue_bot}.get

    for _ in range(3):
        await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.ban, 555))

    cast(MagicMock, event_handlers.quarantine_actions.remove_bot).assert_called_once_with(
        guild, rogue_bot, "ban", event_handlers.action_cache
    )
    cast(MagicMock, event_handlers.quarantine_actions.execute_quarantine).assert_not_called()


@pytest.mark.asyncio
async def test_trusted_bot_is_skipped(
    event_handlers: EventHandlers, config_mock: MagicMock, guild: MagicMock, scheduled: list
) -> None:
    mod_bot = _member(556, bot=True)
    guild.get_member.side_effect = {**guild.members_by_id, 556: mod_bot}.get
    config_mock.guild.return_value.trusted_users = AsyncMock(return_value=[556])

    for _ in range(5):
        await event_handlers.on_audit_log_entry_create(_entry(guild, discord.AuditLogAction.ban, 556))

    assert scheduled == []


# --- bot additions ---


@pytest.mark.asyncio
async def test_bot_add_quarantines_adder_and_kicks_bot(
    event_handlers: EventHandlers, guild: MagicMock, scheduled: list
) -> None:
    await event_handlers.on_audit_log_entry_create(
        _entry(guild, discord.AuditLogAction.bot_add, target=discord.Object(id=777))
    )

    assert [args[2] for args in _quarantined(event_handlers)] == ["bot_add"]
    kick = cast(MagicMock, event_handlers.quarantine_actions.kick_bot)
    kick.assert_called_once()
    assert kick.call_args.args[1].id == 777


@pytest.mark.asyncio
async def test_bot_add_without_botkick_leaves_bot(
    event_handlers: EventHandlers, config_mock: MagicMock, guild: MagicMock, scheduled: list
) -> None:
    monitor = copy.deepcopy(DEFAULT_GUILD["monitor"])
    monitor["bot_add"]["kick_bot"] = False
    config_mock.guild.return_value.monitor = AsyncMock(return_value=monitor)

    await event_handlers.on_audit_log_entry_create(
        _entry(guild, discord.AuditLogAction.bot_add, target=discord.Object(id=777))
    )

    assert [args[2] for args in _quarantined(event_handlers)] == ["bot_add"]
    cast(MagicMock, event_handlers.quarantine_actions.kick_bot).assert_not_called()


# --- trust ---


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


@pytest.mark.asyncio
async def test_bot_add_naming_this_bot_does_not_kick_it(
    event_handlers: EventHandlers, config_mock: MagicMock, guild: MagicMock
) -> None:
    """Even when the adder is punished, the kick of the added bot never targets this bot."""
    event_handlers.quarantine_actions = QuarantineActions(MagicMock(spec=Red), config_mock)
    event_handlers.quarantine_actions.execute_quarantine = AsyncMock(return_value=True)  # type: ignore[method-assign]
    guild.kick = AsyncMock()

    await event_handlers.on_audit_log_entry_create(
        _entry(guild, discord.AuditLogAction.bot_add, target=discord.Object(id=BOT_SELF_ID))
    )
    await asyncio.gather(*event_handlers._background_tasks)

    guild.kick.assert_not_awaited()
