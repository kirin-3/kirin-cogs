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


def _slash_interaction(author: Any, guild: MagicMock) -> MagicMock:
    """Build an interaction whose baton context mirrors a slash invocation."""
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = author
    ctx.bot.is_owner = AsyncMock(return_value=False)
    ctx.bot.is_admin = AsyncMock(return_value=False)
    interaction = MagicMock()
    interaction.client.can_run = AsyncMock(return_value=True)
    interaction._baton = ctx
    return interaction


@pytest.mark.parametrize("command_name", ["honeypot_restore", "honeypot_list", "honeypot_clear"])
def test_subcommands_carry_staff_check(command_name: str) -> None:
    command = getattr(Honeypot, command_name)

    assert _staff_or_admin in command.checks


@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", ["honeypot_restore", "honeypot_list", "honeypot_clear"])
async def test_slash_subcommand_refuses_unauthorized_member(command_name: str) -> None:
    config = _MemoryConfig({GUILD_ID: {"42": {"roles": [10], "state": "completed"}}})
    guild = _guild()
    target = _member(guild)
    author = _member(guild, user_id=7)
    author.get_role.return_value = None
    author.guild_permissions.manage_roles = False
    app_command = getattr(Honeypot, command_name).app_command

    allowed = await app_command._check_can_run(_slash_interaction(author, guild))

    assert allowed is False
    assert config.guild_records[GUILD_ID] == {"42": {"roles": [10], "state": "completed"}}
    target.edit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", ["honeypot_restore", "honeypot_list", "honeypot_clear"])
async def test_slash_subcommand_allows_staff_member(command_name: str) -> None:
    guild = _guild()
    staff_role = _role(STAFF_ROLE_ID, assignable=True)
    author = _member(guild, user_id=7, roles=[staff_role])
    author.get_role.side_effect = lambda role_id: staff_role if role_id == STAFF_ROLE_ID else None
    author.guild_permissions.manage_roles = False
    app_command = getattr(Honeypot, command_name).app_command

    assert await app_command._check_can_run(_slash_interaction(author, guild)) is True


@pytest.mark.asyncio
async def test_banned_user_who_rejoins_is_enforced_again() -> None:
    cog = _make_cog()
    guild = _guild()
    member = _member(guild, joined_at=datetime.now(UTC))
    ban = AsyncMock(return_value=True)

    with patch.object(cog, "_ban_member", ban):
        await cog._handle_trigger(_message(guild, member), member, "Member (42)", "spam", ())
        # The rest of the burst, queued before the ban landed, is only deleted.
        burst = _message(guild, member)
        await cog._handle_trigger(burst, member, "Member (42)", "spam", ())
        burst.delete.assert_awaited_once()
        assert ban.await_count == 1

        # Unbanned and rejoined: a new post is a new incident.
        await cog.on_member_join(member)
        await cog._handle_trigger(_message(guild, member), member, "Member (42)", "spam", ())

    assert ban.await_count == 2


@pytest.mark.asyncio
async def test_quarantine_burst_with_stale_author_roles_edits_once() -> None:
    """Queued burst messages still carry the pre-quarantine roles and must not re-quarantine."""
    config = _MemoryConfig()
    cog = _make_cog(config)
    guild = _guild()
    member = _member(guild, joined_at=None, roles=[_role(10, assignable=True)])

    for _ in range(3):
        await cog._handle_trigger(_message(guild, member), member, "Member (42)", "spam", ())

    member.edit.assert_awaited_once()
    assert config.guild_records[GUILD_ID]["42"]["roles"] == [10]


@pytest.mark.asyncio
async def test_own_quarantine_edit_does_not_release_member() -> None:
    cog = _make_cog()
    guild = _guild()
    before = _member(guild, roles=[_role(10, assignable=True)])
    after = _member(guild, roles=[_role(11, assignable=False)])
    cog._enforced_users.add((GUILD_ID, 42))

    await cog.on_member_update(before, after)

    assert (GUILD_ID, 42) in cog._enforced_users


@pytest.mark.asyncio
async def test_roles_given_back_by_hand_allow_a_new_quarantine() -> None:
    config = _MemoryConfig({GUILD_ID: {"42": {"roles": [10, 20], "state": "completed", "quarantined_at": "then"}}})
    cog = _make_cog(config)
    channel = _log_channel()
    guild = _guild(records_channel=channel)
    cog._enforced_users.add((GUILD_ID, 42))
    contained = _member(guild, joined_at=None, roles=[])
    released = _member(guild, joined_at=None, roles=[_role(10, assignable=True), _role(30, assignable=True)])

    # Staff hand roles back instead of using the restore command.
    await cog.on_member_update(contained, released)
    assert (GUILD_ID, 42) not in cog._enforced_users

    await cog._handle_trigger(_message(guild, released), released, "Member (42)", "spam", ())

    released.edit.assert_awaited_once()
    assert released.edit.call_args.kwargs["roles"] == []
    record = config.guild_records[GUILD_ID]["42"]
    assert record["state"] == "completed"
    # Nothing restorable is lost: the earlier snapshot plus the roles held now.
    assert record["roles"] == [10, 20, 30]
    assert record["quarantined_at"] != "then"
    embed = channel.send.call_args.kwargs["embed"]
    assert any(field.name == "Repeat quarantine" for field in embed.fields)


@pytest.mark.asyncio
async def test_completed_record_with_roles_back_is_enforced_after_restart() -> None:
    config = _MemoryConfig({GUILD_ID: {"42": {"roles": [10], "state": "completed", "quarantined_at": "then"}}})
    cog = _make_cog(config)
    guild = _guild()
    member = _member(guild, joined_at=None, roles=[_role(10, assignable=True)])

    await cog._handle_trigger(_message(guild, member), member, "Member (42)", "spam", ())

    member.edit.assert_awaited_once()
    assert config.guild_records[GUILD_ID]["42"]["roles"] == [10]


def _command_ctx(guild: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = SimpleNamespace(id=7)
    ctx.send = AsyncMock()
    return ctx


def _departed_user(user_id: int = 42) -> MagicMock:
    user = MagicMock(spec=discord.User)
    user.id = user_id
    user.mention = f"<@{user_id}>"
    return user


@pytest.mark.asyncio
async def test_clear_removes_record_for_user_who_left() -> None:
    config = _MemoryConfig({GUILD_ID: {"42": {"roles": [10], "state": "completed"}}})
    cog = _make_cog(config)
    guild = _guild()
    guild.get_member.return_value = None
    cog._enforced_users.add((GUILD_ID, 42))
    ctx = _command_ctx(guild)

    await cast(Any, cog.honeypot_clear).callback(cog, ctx, _departed_user())

    assert config.guild_records[GUILD_ID] == {}
    assert (GUILD_ID, 42) not in cog._enforced_users
    assert "Cleared" in ctx.send.call_args.args[0]


@pytest.mark.asyncio
async def test_restore_for_user_who_left_keeps_record_and_explains() -> None:
    record = {"roles": [10], "state": "completed"}
    config = _MemoryConfig({GUILD_ID: {"42": record.copy()}})
    cog = _make_cog(config)
    guild = _guild()
    guild.get_member.return_value = None
    ctx = _command_ctx(guild)

    await cast(Any, cog.honeypot_restore).callback(cog, ctx, _departed_user())

    assert config.guild_records[GUILD_ID]["42"] == record
    reply = ctx.send.call_args.args[0]
    assert "no longer in the server" in reply
    assert "honeypot clear" in reply


@pytest.mark.parametrize("command_name", ["honeypot_restore", "honeypot_clear"])
def test_restore_and_clear_accept_users_outside_the_server(command_name: str) -> None:
    command = getattr(Honeypot, command_name)

    # The parameter keeps its name so already-synced slash commands keep working.
    annotation = command.clean_params["member"].annotation
    assert discord.User in getattr(annotation, "__args__", (annotation,))
    assert command.app_command.parameters[0].type is discord.AppCommandOptionType.user


@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", ["honeypot_restore", "honeypot_clear"])
async def test_restore_and_clear_wait_for_in_flight_enforcement(command_name: str) -> None:
    config = _MemoryConfig({GUILD_ID: {"42": {"roles": [], "state": "pending", "quarantined_at": "then"}}})
    cog = _make_cog(config)
    guild = _guild(records_channel=_log_channel())
    member = _member(guild)
    ctx = _command_ctx(guild)

    async with cog._quarantine_lock(GUILD_ID, 42):  # enforcement mid-flight
        task = asyncio.create_task(cast(Any, getattr(cog, command_name)).callback(cog, ctx, member))
        for _ in range(5):
            await asyncio.sleep(0)
        assert "42" in config.guild_records[GUILD_ID]
        member.edit.assert_not_awaited()
    await task

    assert "42" not in config.guild_records[GUILD_ID]
    assert not cog._quarantine_locks
