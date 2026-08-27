"""Tests for honeypot detection, enforcement, persistence, and restoration."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest

import honeypot.honeypot as honeypot_module
from honeypot.honeypot import (
    BAN_NOTICE,
    BAN_PURGE_SECONDS,
    GUILD_ID,
    HONEYPOT_CHANNEL_ID,
    LOG_CHANNEL_ID,
    QUARANTINE_NOTICE,
    STAFF_ROLE_ID,
    Honeypot,
    _staff_or_admin,
)


class _MemoryValue:
    """Small awaitable/context-manager stand-in for a Red Config value."""

    def __init__(self, data: Any) -> None:
        self.data = data

    def __call__(self) -> "_MemoryValue":
        return self

    def __await__(self):
        async def read():
            return self.data

        return read().__await__()

    async def __aenter__(self):
        return self.data

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def set(self, value: Any) -> None:
        if isinstance(self.data, dict) and isinstance(value, dict):
            replacement = value.copy()
            self.data.clear()
            self.data.update(replacement)
        else:
            self.data = value


class _MemoryGuildGroup:
    def __init__(self, records: dict[Any, Any]) -> None:
        self.quarantined_users = _MemoryValue(records)


class _MemoryConfig:
    def __init__(self, guild_records: dict[int, dict[Any, Any]] | None = None) -> None:
        self.guild_records = guild_records or {}

    def guild(self, guild: discord.Guild) -> _MemoryGuildGroup:
        return self.guild_from_id(guild.id)

    def guild_from_id(self, guild_id: int) -> _MemoryGuildGroup:
        return _MemoryGuildGroup(self.guild_records.setdefault(guild_id, {}))

    async def all_guilds(self) -> dict[int, dict[str, dict[Any, Any]]]:
        return {guild_id: {"quarantined_users": records} for guild_id, records in self.guild_records.items()}


def _make_cog(config: _MemoryConfig | None = None) -> Honeypot:
    cog = Honeypot.__new__(Honeypot)
    cog.bot = MagicMock()
    cog.config = config or _MemoryConfig()  # type: ignore[assignment]
    cog._quarantine_locks = {}
    cog._background_tasks = set()
    cog._enforced_users = set()
    return cog


def _role(role_id: int, *, assignable: bool, default: bool = False) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.is_assignable.return_value = assignable
    role.is_default.return_value = default
    return role


def _log_channel() -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = LOG_CHANNEL_ID
    channel.send = AsyncMock()
    return channel


def _guild(*, guild_id: int = GUILD_ID, records_channel: MagicMock | None = None) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.owner_id = 999999
    guild.get_channel.return_value = records_channel or _log_channel()
    bot_member = MagicMock(spec=discord.Member)
    bot_member.guild_permissions = SimpleNamespace(
        ban_members=True,
        manage_roles=True,
        moderate_members=True,
        manage_messages=True,
    )
    guild.me = bot_member
    return guild


def _member(
    guild: MagicMock,
    *,
    user_id: int = 42,
    joined_at: datetime | None = None,
    roles: list[MagicMock] | None = None,
) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.mention = f"<@{user_id}>"
    member.bot = False
    member.guild = guild
    member.joined_at = joined_at
    member.roles = roles or []
    member.send = AsyncMock()
    member.edit = AsyncMock()
    guild.get_member.return_value = member
    return member


def _message(
    guild: MagicMock | None,
    author: Any,
    *,
    channel_id: int = HONEYPOT_CHANNEL_ID,
    parent_id: int | None = None,
    webhook_id: int | None = None,
) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.id = 123
    message.guild = guild
    message.author = author
    message.channel = SimpleNamespace(id=channel_id, parent_id=parent_id)
    message.webhook_id = webhook_id
    message.content = "captured spam"
    message.attachments = [SimpleNamespace(filename="payload.png")]
    message.delete = AsyncMock()
    return message


def _forbidden() -> discord.Forbidden:
    response = MagicMock(status=403, reason="Forbidden")
    response.headers = {}
    return discord.Forbidden(response, {"message": "Missing permissions", "code": 50013})


def _http_error() -> discord.HTTPException:
    response = MagicMock(status=500, reason="Server error")
    response.headers = {}
    return discord.HTTPException(response, {"message": "Failure", "code": 0})


@pytest.mark.asyncio
async def test_guard_gauntlet_has_no_side_effects_and_thread_is_accepted() -> None:
    cog = _make_cog()
    guild = _guild()
    member = _member(guild)
    create_task = MagicMock()
    cog._create_task = create_task  # type: ignore[method-assign]

    wrong_guild = _guild(guild_id=GUILD_ID + 1)
    cases = [
        _message(wrong_guild, _member(wrong_guild)),
        _message(guild, member, channel_id=HONEYPOT_CHANNEL_ID + 1),
        _message(None, member),
        _message(guild, _member(guild)),
        _message(guild, member, webhook_id=55),
        _message(guild, SimpleNamespace(bot=False)),
    ]
    cases[3].author.bot = True
    staff_member = _member(guild, roles=[_role(STAFF_ROLE_ID, assignable=True)])
    cases.append(_message(guild, staff_member))

    for message in cases:
        await cog.on_message(message)

    create_task.assert_not_called()
    for message in cases:
        message.delete.assert_not_awaited()

    thread_message = _message(
        guild,
        member,
        channel_id=HONEYPOT_CHANNEL_ID + 99,
        parent_id=HONEYPOT_CHANNEL_ID,
    )
    await cog.on_message(thread_message)
    create_task.assert_called_once()
    create_task.call_args.args[0].close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("joined_at", "expected_path"),
    [
        (datetime.now(UTC) - timedelta(days=3) + timedelta(seconds=30), "ban"),
        (datetime.now(UTC) - timedelta(days=3), "quarantine"),
        (None, "quarantine"),
    ],
)
async def test_tenure_boundary_routes_to_expected_path(joined_at: datetime | None, expected_path: str) -> None:
    cog = _make_cog()
    guild = _guild()
    member = _member(guild, joined_at=joined_at)
    message = _message(guild, member)
    ban = AsyncMock(return_value=True)
    quarantine = AsyncMock(return_value=True)

    with patch.object(cog, "_ban_member", ban), patch.object(cog, "_quarantine_member", quarantine):
        await cog._handle_trigger(message, member, "Member (42)", "spam", ())

    if expected_path == "ban":
        ban.assert_awaited_once()
        quarantine.assert_not_awaited()
    else:
        quarantine.assert_awaited_once()
        ban.assert_not_awaited()


@pytest.mark.asyncio
async def test_guild_owner_is_never_targeted() -> None:
    cog = _make_cog()
    guild = _guild()
    member = _member(guild)
    guild.owner_id = member.id
    message = _message(guild, member)
    alert = AsyncMock()

    with (
        patch.object(cog, "_log_alert", alert),
        patch.object(cog, "_ban_member", new=AsyncMock()) as ban,
        patch.object(cog, "_quarantine_member", new=AsyncMock()) as quarantine,
    ):
        await cog._handle_trigger(message, member, "Owner (42)", "spam", ())

    alert.assert_awaited_once()
    ban.assert_not_awaited()
    quarantine.assert_not_awaited()


def test_role_partition_keeps_unassignable_roles_and_snapshots_assignable_roles() -> None:
    guild = _guild()
    everyone = _role(1, assignable=False, default=True)
    managed = _role(2, assignable=False)
    above_bot = _role(3, assignable=False)
    removable = _role(4, assignable=True)
    member = _member(guild, roles=[everyone, managed, above_bot, removable])

    keep, snapshot = Honeypot._partition_roles(member)

    # @everyone is implicit; Discord rejects it in a member roles payload.
    assert everyone not in keep
    assert keep == [managed, above_bot]
    assert snapshot == [4]


@pytest.mark.asyncio
async def test_staff_or_admin_check_accepts_staff_red_admin_and_manage_roles() -> None:
    guild = _guild()
    ctx = MagicMock()
    ctx.guild = guild
    ctx.bot.is_owner = AsyncMock(return_value=False)
    ctx.bot.is_admin = AsyncMock(return_value=False)

    staff = _member(guild, roles=[_role(STAFF_ROLE_ID, assignable=True)])
    staff.get_role.side_effect = lambda role_id: staff.roles[0] if role_id == STAFF_ROLE_ID else None
    staff.guild_permissions.manage_roles = False
    ctx.author = staff
    assert await _staff_or_admin(ctx) is True

    manager = _member(guild, roles=[])
    manager.get_role.return_value = None
    manager.guild_permissions.manage_roles = True
    ctx.author = manager
    assert await _staff_or_admin(ctx) is True

    admin = _member(guild, roles=[])
    admin.get_role.return_value = None
    admin.guild_permissions.manage_roles = False
    ctx.author = admin
    ctx.bot.is_admin.return_value = True
    assert await _staff_or_admin(ctx) is True


@pytest.mark.asyncio
async def test_quarantine_writes_pending_before_one_atomic_edit_and_completes() -> None:
    config = _MemoryConfig()
    cog = _make_cog(config)
    channel = _log_channel()
    guild = _guild(records_channel=channel)
    removable = _role(10, assignable=True)
    retained = _role(11, assignable=False)
    member = _member(guild, roles=[retained, removable])

    async def assert_pending_before_edit(**kwargs: Any) -> None:
        record = config.guild_records[guild.id][str(member.id)]
        assert record["state"] == "pending"
        assert record["roles"] == [10]

    member.edit.side_effect = assert_pending_before_edit

    result = await cog._quarantine_member(guild, member, "Member (42)", "spam", ("file.png",), None)

    assert result is True
    member.edit.assert_awaited_once()
    call = member.edit.call_args
    assert call.kwargs["roles"] == [retained]
    assert call.kwargs["timed_out_until"] is not None
    assert config.guild_records[guild.id][str(member.id)]["state"] == "completed"
    member.send.assert_awaited_once_with(QUARANTINE_NOTICE)


@pytest.mark.asyncio
async def test_quarantine_with_no_assignable_roles_still_applies_timeout() -> None:
    config = _MemoryConfig()
    cog = _make_cog(config)
    guild = _guild()
    retained = _role(11, assignable=False)
    member = _member(guild, roles=[retained])

    result = await cog._quarantine_member(guild, member, "Member (42)", "spam", (), None)

    assert result is True
    member.edit.assert_awaited_once()
    assert member.edit.call_args.kwargs["roles"] == [retained]
    assert member.edit.call_args.kwargs["timed_out_until"] is not None
    assert config.guild_records[GUILD_ID]["42"]["roles"] == []


def test_embed_field_content_is_truncated_without_being_dropped() -> None:
    value = Honeypot._field_value("x" * 2000)

    assert len(value) == 1024
    assert value.endswith("…")


@pytest.mark.asyncio
async def test_quarantine_failure_retains_snapshot_and_marks_failed() -> None:
    config = _MemoryConfig()
    cog = _make_cog(config)
    guild = _guild()
    member = _member(guild, roles=[_role(10, assignable=True)])
    member.edit.side_effect = _http_error()

    result = await cog._quarantine_member(guild, member, "Member (42)", "spam", (), None)

    assert result is False
    record = config.guild_records[guild.id][str(member.id)]
    assert record["state"] == "failed"
    assert record["roles"] == [10]
    assert "last_error" in record
    member.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_reuses_failed_snapshot_instead_of_current_roles() -> None:
    config = _MemoryConfig({GUILD_ID: {"42": {"roles": [10], "state": "failed", "quarantined_at": "earlier"}}})
    cog = _make_cog(config)
    guild = _guild()
    member = _member(guild, roles=[_role(99, assignable=True)])

    await cog._quarantine_member(
        guild,
        member,
        "Member (42)",
        "spam",
        (),
        config.guild_records[GUILD_ID]["42"],
    )

    assert config.guild_records[GUILD_ID]["42"]["roles"] == [10]


@pytest.mark.asyncio
async def test_completed_snapshot_is_not_overwritten_by_second_trigger() -> None:
    original = {"roles": [10, 20], "state": "completed", "quarantined_at": "original"}
    config = _MemoryConfig({GUILD_ID: {"42": original.copy()}})
    cog = _make_cog(config)
    guild = _guild()
    member = _member(guild, joined_at=None, roles=[])
    message = _message(guild, member)

    await cog._handle_trigger(message, member, "Member (42)", "second spam", ())

    message.delete.assert_awaited_once()
    member.edit.assert_not_awaited()
    assert config.guild_records[GUILD_ID]["42"] == original


@pytest.mark.asyncio
async def test_ten_message_burst_runs_one_enforcement_action() -> None:
    cog = _make_cog()
    guild = _guild()
    member = _member(guild, joined_at=None)
    messages = [_message(guild, member) for _ in range(10)]

    async def quarantine_once(*args: Any, **kwargs: Any) -> bool:
        await asyncio.sleep(0)
        return True

    quarantine = AsyncMock(side_effect=quarantine_once)
    with patch.object(cog, "_quarantine_member", quarantine):
        await asyncio.gather(*(cog._handle_trigger(message, member, "Member (42)", "spam", ()) for message in messages))

    quarantine.assert_awaited_once()
    assert all(message.delete.await_count == 1 for message in messages)
    assert not cog._quarantine_locks


@pytest.mark.asyncio
async def test_ban_dm_failure_does_not_prevent_ban_or_add_fallback() -> None:
    cog = _make_cog()
    channel = _log_channel()
    guild = _guild(records_channel=channel)
    member = _member(guild)
    member.send.side_effect = _forbidden()
    guild.ban = AsyncMock()

    result = await cog._ban_member(guild, member, "Member (42)", "spam", (), 1.0)

    assert result is True
    member.send.assert_awaited_once_with(BAN_NOTICE)
    guild.ban.assert_awaited_once_with(
        member,
        reason="Posted in the Unicornia honeypot channel",
        delete_message_seconds=BAN_PURGE_SECONDS,
    )
    channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_ban_uses_user_object_when_member_has_left() -> None:
    cog = _make_cog()
    guild = _guild()
    member = _member(guild)
    guild.get_member.return_value = None
    guild.ban = AsyncMock()

    await cog._ban_member(guild, member, "Member (42)", "spam", (), 1.0)

    target = guild.ban.call_args.args[0]
    assert isinstance(target, discord.Object)
    assert target.id == member.id


@pytest.mark.asyncio
async def test_quarantine_dm_failure_does_not_reverse_success() -> None:
    config = _MemoryConfig()
    cog = _make_cog(config)
    guild = _guild()
    member = _member(guild, roles=[_role(10, assignable=True)])
    member.send.side_effect = _forbidden()

    result = await cog._quarantine_member(guild, member, "Member (42)", "spam", (), None)

    assert result is True
    member.edit.assert_awaited_once()
    member.send.assert_awaited_once_with(QUARANTINE_NOTICE)
    assert config.guild_records[GUILD_ID]["42"]["state"] == "completed"


@pytest.mark.asyncio
async def test_restore_unions_current_roles_skips_unrestorable_and_clears_timeout() -> None:
    config = _MemoryConfig({GUILD_ID: {"42": {"roles": [10, 20, 30], "state": "completed", "quarantined_at": "then"}}})
    cog = _make_cog(config)
    channel = _log_channel()
    guild = _guild(records_channel=channel)
    everyone = _role(1, assignable=False, default=True)
    current = _role(40, assignable=False)
    restorable = _role(10, assignable=True)
    unassignable = _role(30, assignable=False)
    member = _member(guild, roles=[everyone, current])
    guild.get_role.side_effect = {10: restorable, 20: None, 30: unassignable}.get
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = SimpleNamespace(id=7, __str__=lambda self: "Moderator")
    ctx.send = AsyncMock()

    await cast(Any, cog.honeypot_restore).callback(cog, ctx, member)

    member.edit.assert_awaited_once()
    # @everyone is implicit; Discord rejects it in a member roles payload.
    assert everyone not in member.edit.call_args.kwargs["roles"]
    assert member.edit.call_args.kwargs["roles"] == [current, restorable]
    assert member.edit.call_args.kwargs["timed_out_until"] is None
    assert "42" not in config.guild_records[GUILD_ID]
    assert "2 role(s)" in ctx.send.call_args.args[0]
    channel.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_failure_retains_record() -> None:
    record = {"roles": [10], "state": "completed", "quarantined_at": "then"}
    config = _MemoryConfig({GUILD_ID: {"42": record.copy()}})
    cog = _make_cog(config)
    guild = _guild()
    member = _member(guild)
    guild.get_role.return_value = _role(10, assignable=True)
    member.edit.side_effect = _forbidden()
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = SimpleNamespace(id=7)
    ctx.send = AsyncMock()

    await cast(Any, cog.honeypot_restore).callback(cog, ctx, member)

    assert config.guild_records[GUILD_ID]["42"] == record
    assert "retained" in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_data_deletion_removes_records_from_all_guilds() -> None:
    config = _MemoryConfig(
        {
            1: {"42": {"roles": [10]}, "99": {"roles": [20]}},
            2: {42: {"roles": [30]}},
        }
    )
    cog = _make_cog(config)

    await cog.red_delete_data_for_user(requester="user", user_id=42)

    assert config.guild_records[1] == {"99": {"roles": [20]}}
    assert config.guild_records[2] == {}


@pytest.mark.asyncio
async def test_dpytest_dispatches_matching_message_to_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    intents.messages = True
    intents.message_content = True
    bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(bot)

    cog = _make_cog()
    cog.bot = bot  # type: ignore[assignment]
    handler = AsyncMock()
    cog._handle_trigger = handler  # type: ignore[method-assign]
    guild = dpytest.get_config().guilds[0]
    channel = dpytest.get_config().channels[0]
    monkeypatch.setattr(honeypot_module, "GUILD_ID", guild.id)
    monkeypatch.setattr(honeypot_module, "HONEYPOT_CHANNEL_ID", channel.id)
    await bot.add_cog(cog)

    await dpytest.message("tripwire")
    await dpytest.run_all_events()
    pending = list(cog._background_tasks)
    if pending:
        await asyncio.gather(*pending)

    handler.assert_awaited_once()
    await dpytest.empty_queue()
