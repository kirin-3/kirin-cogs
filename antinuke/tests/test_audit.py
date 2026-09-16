"""Unit tests for the AuditLogHelper class."""

import time
from unittest.mock import MagicMock

import discord
import pytest
from redbot.core import Config
from redbot.core.bot import Red

from antinuke.audit import AuditLogHelper


@pytest.fixture
def bot_mock():
    return MagicMock(spec=Red)


@pytest.fixture
def config_mock():
    return MagicMock(spec=Config)


@pytest.fixture
def audit_helper(bot_mock, config_mock):
    return AuditLogHelper(bot_mock, config_mock)


@pytest.mark.asyncio
async def test_get_channel_delete_culprit_below_threshold(audit_helper):
    # Setup mock guild
    guild = MagicMock(spec=discord.Guild)

    # Create mock user
    user = MagicMock(spec=discord.Member)
    user.bot = False
    user.id = 123

    # Create mock audit log entry within timeframe
    entry = MagicMock(spec=discord.AuditLogEntry)
    entry.user = user
    entry.created_at.timestamp.return_value = time.time()

    # Mock audit_logs to yield the entry
    async def mock_audit_logs(*args, **kwargs):
        yield entry

    guild.audit_logs = mock_audit_logs
    guild.get_member.return_value = user

    # Threshold is 2, but only 1 action found
    culprits = await audit_helper.get_channel_delete_culprit(guild, timeframe=60, threshold=2)

    assert len(culprits) == 0


@pytest.mark.asyncio
async def test_get_channel_delete_culprit_above_threshold(audit_helper):
    guild = MagicMock(spec=discord.Guild)

    user = MagicMock(spec=discord.Member)
    user.bot = False
    user.id = 123

    entry = MagicMock(spec=discord.AuditLogEntry)
    entry.user = user
    entry.created_at.timestamp.return_value = time.time()

    async def mock_audit_logs(*args, **kwargs):
        for _ in range(3):
            yield entry

    guild.audit_logs = mock_audit_logs
    guild.get_member.return_value = user

    # Threshold is 2, 3 actions found
    culprits = await audit_helper.get_channel_delete_culprit(guild, timeframe=60, threshold=2)

    assert len(culprits) == 1
    assert culprits[0][0] == user
    assert culprits[0][1] == 3


@pytest.mark.asyncio
async def test_get_channel_delete_culprit_outside_timeframe(audit_helper):
    guild = MagicMock(spec=discord.Guild)

    user = MagicMock(spec=discord.Member)
    user.bot = False
    user.id = 123

    entry = MagicMock(spec=discord.AuditLogEntry)
    entry.user = user
    # Older than the 60s timeframe
    entry.created_at.timestamp.return_value = time.time() - 100

    async def mock_audit_logs(*args, **kwargs):
        for _ in range(3):
            yield entry

    guild.audit_logs = mock_audit_logs
    guild.get_member.return_value = user

    culprits = await audit_helper.get_channel_delete_culprit(guild, timeframe=60, threshold=2)

    assert len(culprits) == 0


@pytest.mark.asyncio
async def test_get_prune_culprit(audit_helper):
    guild = MagicMock(spec=discord.Guild)

    user = MagicMock(spec=discord.Member)
    user.bot = False
    user.id = 123

    entry = MagicMock(spec=discord.AuditLogEntry)
    entry.user = user
    entry.created_at.timestamp.return_value = time.time()

    async def mock_audit_logs(*args, **kwargs):
        yield entry

    guild.audit_logs = mock_audit_logs
    guild.get_member.return_value = user

    culprit = await audit_helper.get_prune_culprit(guild, timeframe=60)

    assert culprit == user


@pytest.mark.asyncio
async def test_get_role_update_dangerous_permissions(audit_helper):
    guild = MagicMock(spec=discord.Guild)

    user = MagicMock(spec=discord.Member)
    user.bot = False
    user.id = 123

    target_role = MagicMock(spec=discord.Role)
    target_role.id = 456

    entry = MagicMock(spec=discord.AuditLogEntry)
    entry.target = target_role
    entry.user = user
    entry.created_at.timestamp.return_value = time.time()

    # Mock entry.before and entry.after for permission check
    entry.before = MagicMock()
    entry.before.permissions = discord.Permissions(0)

    entry.after = MagicMock()
    # Adding administrator permission
    entry.after.permissions = discord.Permissions(administrator=True)

    async def mock_audit_logs(*args, **kwargs):
        yield entry

    guild.audit_logs = mock_audit_logs
    guild.get_member.return_value = user

    result = await audit_helper.get_role_update_culprit(
        guild, role_id=456, timeframe=60, dangerous_perms=["administrator"]
    )

    assert result is not None
    assert result[0] == user
    assert result[1] == "administrator"


@pytest.mark.asyncio
async def test_get_audit_forbidden(audit_helper):
    guild = MagicMock(spec=discord.Guild)

    # Simulate Missing Permissions error
    async def mock_audit_logs(*args, **kwargs):
        raise discord.Forbidden(MagicMock(), "Missing Permissions")
        yield None

    guild.audit_logs = mock_audit_logs

    culprits = await audit_helper.get_channel_delete_culprit(guild, timeframe=60, threshold=2)

    assert len(culprits) == 0


def _audit_user(user_id: int, *, bot: bool) -> MagicMock:
    user = MagicMock(spec=discord.Member)
    user.id = user_id
    user.bot = bot
    return user


def _entries_guild(entries: list[MagicMock], members: dict[int, MagicMock]) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1

    async def mock_audit_logs(*args, **kwargs):
        for entry in entries:
            yield entry

    guild.audit_logs = mock_audit_logs
    guild.get_member.side_effect = members.get
    return guild


def _entry(user: MagicMock | None, **attrs) -> MagicMock:
    entry = MagicMock(spec=discord.AuditLogEntry)
    entry.user = user
    entry.created_at.timestamp.return_value = time.time()
    for name, value in attrs.items():
        setattr(entry, name, value)
    return entry


@pytest.mark.asyncio
async def test_bot_only_entries_produce_no_culprit(audit_helper):
    bot_user = _audit_user(900, bot=True)
    guild = _entries_guild([_entry(bot_user) for _ in range(5)] + [_entry(None)], {900: bot_user})

    assert await audit_helper.get_ban_culprit(guild, timeframe=60, threshold=2) == []


@pytest.mark.asyncio
async def test_mixed_entries_count_only_humans(audit_helper):
    bot_user = _audit_user(900, bot=True)
    human = _audit_user(123, bot=False)
    entries = [_entry(bot_user), _entry(human), _entry(bot_user), _entry(human), _entry(bot_user)]
    guild = _entries_guild(entries, {900: bot_user, 123: human})

    assert await audit_helper.get_ban_culprit(guild, timeframe=60, threshold=2) == [(human, 2)]


@pytest.mark.asyncio
async def test_role_update_by_bot_is_not_attributed(audit_helper):
    bot_user = _audit_user(900, bot=True)
    target = MagicMock(spec=discord.Role)
    target.id = 456
    before = MagicMock()
    before.permissions = discord.Permissions(0)
    after = MagicMock()
    after.permissions = discord.Permissions(administrator=True)
    guild = _entries_guild([_entry(bot_user, target=target, before=before, after=after)], {900: bot_user})

    assert await audit_helper.get_role_update_culprit(guild, role_id=456, timeframe=60) is None


@pytest.mark.asyncio
async def test_vanity_change_by_bot_is_not_attributed(audit_helper):
    bot_user = _audit_user(900, bot=True)
    after = MagicMock()
    after.vanity_url_code = "new"
    guild = _entries_guild([_entry(bot_user, after=after)], {900: bot_user})

    assert await audit_helper.get_vanity_change_culprit(guild, timeframe=60) is None


@pytest.mark.asyncio
async def test_bot_add_by_bot_is_not_attributed(audit_helper):
    bot_user = _audit_user(900, bot=True)
    added = MagicMock()
    added.id = 777
    guild = _entries_guild([_entry(bot_user, target=added)], {900: bot_user})

    assert await audit_helper.get_bot_add_culprit(guild, bot_id=777, timeframe=60) is None
