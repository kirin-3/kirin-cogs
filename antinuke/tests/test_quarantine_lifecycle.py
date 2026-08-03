"""Quarantine state-machine, concurrency, and task-lifecycle tests (5.5)."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from redbot.core import Config
from redbot.core.bot import Red

from antinuke.actions import QuarantineActions
from antinuke.events import EventHandlers

# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------


class ConfigGroupMock(dict):
    """Supports both ``await group()`` and ``async with group()``."""

    async def __aenter__(self) -> "ConfigGroupMock":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        pass

    def __await__(self):  # type: ignore[override]
        async def get_dict() -> "ConfigGroupMock":
            return self

        return get_dict().__await__()


@pytest.fixture
def bot_mock() -> MagicMock:
    return MagicMock(spec=Red)


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.guild.return_value.quarantine_role = AsyncMock(return_value=999)
    config.guild.return_value.log_channel = AsyncMock(return_value=None)
    group_mock: ConfigGroupMock = ConfigGroupMock()
    config.guild.return_value.quarantined_users = MagicMock(return_value=group_mock)
    return config


@pytest.fixture
def actions(bot_mock: MagicMock, config_mock: MagicMock) -> QuarantineActions:
    qa = QuarantineActions(bot_mock, config_mock)
    qa.notify_owner_hierarchy_issue = AsyncMock()  # type: ignore[method-assign]
    qa.log_quarantine = AsyncMock()  # type: ignore[method-assign]
    qa.log_restoration = AsyncMock()  # type: ignore[method-assign]
    return qa


def _role(role_id: int) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    return role


def _guild(*, q_role_id: int = 999, role_map: dict[int, MagicMock] | None = None) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1

    bot_member = MagicMock(spec=discord.Member)
    bot_member.top_role = MagicMock()
    # Bot top role outranks everything by default
    bot_member.top_role.__gt__.return_value = True
    bot_member.top_role.__le__.return_value = False
    guild.me = bot_member

    guild.default_role = _role(0)

    mapping = dict(role_map or {})
    q_role = _role(q_role_id)
    mapping.setdefault(q_role_id, q_role)
    guild.get_role.side_effect = lambda rid: mapping.get(rid) or _role(rid)
    return guild


def _member(user_id: int = 123, roles: list | None = None) -> MagicMock:
    user = MagicMock(spec=discord.Member)
    user.id = user_id
    user.top_role = MagicMock()
    user.roles = roles if roles is not None else []
    user.edit = AsyncMock()
    return user


async def _drain(actions: QuarantineActions) -> None:
    tasks = list(actions._background_tasks)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Concurrent quarantine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_quarantine_keeps_first_snapshot(actions: QuarantineActions, config_mock: MagicMock) -> None:
    """Two overlapping quarantines: one edit, one snapshot, state completed."""
    guild = _guild()
    original_roles = [guild.default_role, _role(101), _role(102)]
    user = _member(roles=original_roles)

    edits = 0
    gate = asyncio.Event()

    async def slow_edit(**kwargs: Any) -> None:
        nonlocal edits
        edits += 1
        await gate.wait()

    user.edit = slow_edit

    first = asyncio.create_task(actions.execute_quarantine(guild, user, "ban"))
    await asyncio.sleep(0)  # let the first reach the Discord edit
    second = asyncio.create_task(actions.execute_quarantine(guild, user, "ban"))
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(first, second)
    await _drain(actions)

    assert results == [True, True]
    assert edits == 1  # exactly one Discord edit captured the snapshot

    stored = config_mock.guild.return_value.quarantined_users.return_value[str(user.id)]
    assert stored["roles"] == [101, 102]
    assert stored["state"] == "completed"
    assert "completed_at" in stored

    # Idle lock entries were cleaned up
    assert actions._quarantine_locks == {}


@pytest.mark.asyncio
async def test_completed_quarantine_is_idempotent(actions: QuarantineActions, config_mock: MagicMock) -> None:
    """A second quarantine after completion preserves the original snapshot."""
    guild = _guild()
    user = _member(roles=[guild.default_role, _role(101)])

    assert await actions.execute_quarantine(guild, user, "ban") is True
    # Member now wears only the quarantine role
    user.roles = [guild.default_role, _role(999)]

    assert await actions.execute_quarantine(guild, user, "kick") is True
    user.edit.assert_awaited_once()  # no second Discord edit

    stored = config_mock.guild.return_value.quarantined_users.return_value[str(user.id)]
    assert stored["roles"] == [101]
    await _drain(actions)


@pytest.mark.asyncio
async def test_legacy_record_without_state_is_treated_completed(
    actions: QuarantineActions, config_mock: MagicMock
) -> None:
    """Pre-state-model records are already-quarantined and never overwritten."""
    guild = _guild()
    user = _member(roles=[_role(0), _role(999)])

    q_users = config_mock.guild.return_value.quarantined_users.return_value
    q_users[str(user.id)] = {"roles": [555], "reason": "legacy"}  # no "state" key

    assert await actions.execute_quarantine(guild, user, "ban") is True
    user.edit.assert_not_awaited()
    assert q_users[str(user.id)]["roles"] == [555]


# ---------------------------------------------------------------------------
# Failure and retry transitions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discord_failure_marks_failed_and_retains_snapshot(
    actions: QuarantineActions, config_mock: MagicMock
) -> None:
    """A failed edit leaves no completed marker and supports a safe retry."""
    guild = _guild()
    user = _member(roles=[guild.default_role, _role(101), _role(102)])
    user.edit = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "server error"))

    result = await actions.execute_quarantine(guild, user, "ban")
    assert result is False

    stored = config_mock.guild.return_value.quarantined_users.return_value[str(user.id)]
    assert stored["state"] == "failed"
    assert stored["roles"] == [101, 102]
    assert "completed_at" not in stored

    # Retry after Discord recovers: same snapshot, now completes.
    user.edit = AsyncMock()
    user.roles = [guild.default_role, _role(999)]  # Discord partially applied earlier
    result = await actions.execute_quarantine(guild, user, "ban")
    assert result is True

    stored = config_mock.guild.return_value.quarantined_users.return_value[str(user.id)]
    assert stored["state"] == "completed"
    assert stored["roles"] == [101, 102]  # first snapshot survived the retry
    await _drain(actions)


@pytest.mark.asyncio
async def test_forbidden_marks_failed_and_notifies(actions: QuarantineActions, config_mock: MagicMock) -> None:
    guild = _guild()
    user = _member(roles=[guild.default_role, _role(101)])
    user.edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "missing access"))

    result = await actions.execute_quarantine(guild, user, "ban")
    assert result is False

    stored = config_mock.guild.return_value.quarantined_users.return_value[str(user.id)]
    assert stored["state"] == "failed"
    assert stored["last_error"] == "forbidden"
    actions.notify_owner_hierarchy_issue.assert_awaited_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Audit counts from the preserved pre-edit role set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stripped_count_comes_from_preserved_snapshot(actions: QuarantineActions) -> None:
    guild = _guild()
    user = _member(roles=[guild.default_role, _role(101), _role(102)])

    await actions.execute_quarantine(guild, user, "ban")
    await _drain(actions)

    # Member now only wears quarantine, but the audit used the snapshot
    actions.log_quarantine.assert_awaited_once()  # type: ignore[attr-defined]
    assert actions.log_quarantine.call_args[0][3] == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_stripped_count_zero_roles(actions: QuarantineActions) -> None:
    guild = _guild()
    user = _member(roles=[guild.default_role])  # only @everyone

    await actions.execute_quarantine(guild, user, "ban")
    await _drain(actions)

    assert actions.log_quarantine.call_args[0][3] == 0  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_stripped_count_excludes_unmanageable_roles(actions: QuarantineActions) -> None:
    guild = _guild()
    user = _member(roles=[guild.default_role, _role(101), _role(102)])

    # Role 102 is above the bot: it cannot be stripped and is not counted.
    guild.me.top_role.__gt__.side_effect = lambda other: getattr(other, "id", 0) != 102

    await actions.execute_quarantine(guild, user, "ban")
    await _drain(actions)

    assert actions.log_quarantine.call_args[0][3] == 1  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Restoration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restore_after_completed_quarantine(actions: QuarantineActions, config_mock: MagicMock) -> None:
    guild = _guild(role_map={101: _role(101), 102: _role(102)})
    user = _member(roles=[guild.default_role, _role(101), _role(102)])

    assert await actions.execute_quarantine(guild, user, "ban") is True
    user.roles = [guild.default_role, guild.get_role(999)]

    assert await actions.restore_user(guild, user, "test") is True

    q_users = config_mock.guild.return_value.quarantined_users.return_value
    assert str(user.id) not in q_users

    # Final role set restored both original roles
    final_call = user.edit.call_args_list[-1]
    final_roles = final_call.kwargs["roles"] if final_call.kwargs else final_call[1]["roles"]
    assert {r.id for r in final_roles} == {101, 102}
    await _drain(actions)


# ---------------------------------------------------------------------------
# Task lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_done_callback_retrieves_exceptions(bot_mock: MagicMock, config_mock: MagicMock) -> None:
    qa = QuarantineActions(bot_mock, config_mock)

    async def _failing() -> None:
        raise RuntimeError("kaboom")

    logged: list[str] = []
    import antinuke.actions as actions_mod

    original_error = actions_mod.log.error
    actions_mod.log.error = lambda *a, **kw: logged.append(str(a))  # type: ignore[assignment]
    try:
        qa._create_task(_failing())
        await asyncio.gather(*list(qa._background_tasks), return_exceptions=True)
        await asyncio.sleep(0)  # allow done callbacks to run
    finally:
        actions_mod.log.error = original_error  # type: ignore[assignment]

    assert any("kaboom" in entry for entry in logged)
    assert qa._background_tasks == set()


@pytest.mark.asyncio
async def test_cancel_all_tasks_cancels_and_gathers(bot_mock: MagicMock, config_mock: MagicMock) -> None:
    qa = QuarantineActions(bot_mock, config_mock)

    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def _worker() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    qa._create_task(_worker())
    await started.wait()

    await qa.cancel_all_tasks()

    assert cancelled.is_set()
    assert qa._background_tasks == set()
    assert qa._quarantine_locks == {}


@pytest.mark.asyncio
async def test_event_handlers_cancel_all_tasks(bot_mock: MagicMock, config_mock: MagicMock) -> None:
    handlers = EventHandlers(bot_mock, config_mock, MagicMock(), MagicMock(), MagicMock())

    started = asyncio.Event()

    async def _worker() -> None:
        started.set()
        await asyncio.Event().wait()

    handlers._create_task(_worker())
    await started.wait()

    await handlers.cancel_all_tasks()
    assert handlers._background_tasks == set()


@pytest.mark.asyncio
async def test_event_handler_task_exception_is_logged(bot_mock: MagicMock, config_mock: MagicMock) -> None:
    handlers = EventHandlers(bot_mock, config_mock, MagicMock(), MagicMock(), MagicMock())

    async def _failing() -> None:
        raise ValueError("investigator exploded")

    logged: list[str] = []
    import antinuke.events as events_mod

    original_error = events_mod.log.error
    events_mod.log.error = lambda *a, **kw: logged.append(str(a))  # type: ignore[assignment]
    try:
        handlers._create_task(_failing())
        await asyncio.gather(*list(handlers._background_tasks), return_exceptions=True)
        await asyncio.sleep(0)
    finally:
        events_mod.log.error = original_error  # type: ignore[assignment]

    assert any("investigator exploded" in entry for entry in logged)
