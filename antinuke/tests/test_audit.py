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
    user.id = 123
    user.bot = False

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
