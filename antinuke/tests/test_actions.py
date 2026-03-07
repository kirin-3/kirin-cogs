"""Unit tests for the QuarantineActions class."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from redbot.core import Config
from redbot.core.bot import Red

from antinuke.actions import QuarantineActions


@pytest.fixture
def bot_mock() -> MagicMock:
    return MagicMock(spec=Red)


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)

    # Mocking Config.guild(guild).quarantine_role() which is awaited
    config.guild.return_value.quarantine_role = AsyncMock(return_value=999)

    # Needs to support both `await` and `async with`
    class ConfigGroupMock(dict):
        async def __aenter__(self) -> "ConfigGroupMock":
            return self

        async def __aexit__(
            self,
            exc_type: object,
            exc: object,
            tb: object,
        ) -> None:
            pass

        def __await__(self):  # type: ignore[override]
            async def get_dict() -> "ConfigGroupMock":
                return self

            return get_dict().__await__()

    group_mock: ConfigGroupMock = ConfigGroupMock()
    config.guild.return_value.quarantined_users = MagicMock(return_value=group_mock)

    return config


@pytest.fixture
def actions(bot_mock: MagicMock, config_mock: MagicMock) -> QuarantineActions:
    return QuarantineActions(bot_mock, config_mock)


@pytest.mark.asyncio
async def test_execute_quarantine_success(
    actions: QuarantineActions, config_mock: MagicMock
) -> None:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1

    bot_member = MagicMock(spec=discord.Member)
    bot_member.top_role = MagicMock()
    # Bot top role > everything
    bot_member.top_role.__gt__.return_value = True
    bot_member.top_role.__le__.return_value = False

    guild.me = bot_member

    user = MagicMock(spec=discord.Member)
    user.id = 123
    user.top_role = MagicMock()

    default_role = MagicMock(spec=discord.Role)
    default_role.id = 0
    guild.default_role = default_role

    user_role1 = MagicMock(spec=discord.Role)
    user_role1.id = 101
    user_role2 = MagicMock(spec=discord.Role)
    user_role2.id = 102
    user.roles = [default_role, user_role1, user_role2]

    q_role = MagicMock(spec=discord.Role)
    q_role.id = 999
    guild.get_role.return_value = q_role

    user.edit = AsyncMock()

    actions.notify_owner_hierarchy_issue = AsyncMock()  # type: ignore[method-assign]
    actions.log_quarantine = AsyncMock()  # type: ignore[method-assign]

    result = await actions.execute_quarantine(guild, user, "channel_delete")

    assert result is True
    user.edit.assert_called_once_with(
        roles=[q_role], reason="AntiNuke: Channel Deletion threshold exceeded"
    )

    q_users_ctx = config_mock.guild.return_value.quarantined_users.return_value
    assert str(user.id) in q_users_ctx
    assert q_users_ctx[str(user.id)]["roles"] == [101, 102]


@pytest.mark.asyncio
async def test_execute_quarantine_hierarchy_fail(actions: QuarantineActions) -> None:
    guild = MagicMock(spec=discord.Guild)

    bot_member = MagicMock(spec=discord.Member)
    bot_member.top_role = MagicMock()

    user = MagicMock(spec=discord.Member)
    user.top_role = MagicMock()

    # Bot top role is NOT > user top role
    bot_member.top_role.__gt__.return_value = False

    guild.me = bot_member

    actions.notify_owner_hierarchy_issue = AsyncMock()  # type: ignore[method-assign]

    result = await actions.execute_quarantine(guild, user, "ban")

    assert result is False
    cast(AsyncMock, actions.notify_owner_hierarchy_issue).assert_called_once()


@pytest.mark.asyncio
async def test_execute_quarantine_no_role_configured(
    actions: QuarantineActions, config_mock: MagicMock
) -> None:
    """Returns False and logs a warning when no quarantine role is set."""
    guild = MagicMock(spec=discord.Guild)

    bot_member = MagicMock(spec=discord.Member)
    bot_member.top_role = MagicMock()
    bot_member.top_role.__gt__.return_value = True
    guild.me = bot_member

    user = MagicMock(spec=discord.Member)
    user.top_role = MagicMock()

    # No quarantine role configured
    config_mock.guild.return_value.quarantine_role = AsyncMock(return_value=None)

    result = await actions.execute_quarantine(guild, user, "channel_delete")

    assert result is False


@pytest.mark.asyncio
async def test_execute_quarantine_role_above_bot(
    actions: QuarantineActions, config_mock: MagicMock
) -> None:
    """Returns False when the quarantine role is at or above the bot's top role."""
    guild = MagicMock(spec=discord.Guild)

    bot_member = MagicMock(spec=discord.Member)
    bot_top = MagicMock(spec=discord.Role)
    # is_above_in_hierarchy passes (bot > user), but quarantine role >= bot top role
    bot_member.top_role = bot_top
    bot_top.__gt__.return_value = True  # bot > user  (hierarchy check passes)
    bot_top.__le__.return_value = True  # bot <= q_role  (quarantine role check fails)
    guild.me = bot_member

    user = MagicMock(spec=discord.Member)
    user.top_role = MagicMock()
    user.roles = [MagicMock(spec=discord.Role, id=101)]

    q_role = MagicMock(spec=discord.Role)
    q_role.id = 999
    guild.get_role.return_value = q_role
    guild.default_role = MagicMock(spec=discord.Role, id=0)

    config_mock.guild.return_value.quarantine_role = AsyncMock(return_value=999)

    result = await actions.execute_quarantine(guild, user, "ban")

    assert result is False


@pytest.mark.asyncio
async def test_restore_user_success(
    actions: QuarantineActions, config_mock: MagicMock
) -> None:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1

    bot_member = MagicMock(spec=discord.Member)
    bot_member.top_role = MagicMock()
    bot_member.top_role.__gt__.return_value = True
    guild.me = bot_member

    user = MagicMock(spec=discord.Member)
    user.id = 123

    # Setup stored quarantine data
    q_users_dict = config_mock.guild.return_value.quarantined_users.return_value
    q_users_dict[str(user.id)] = {"roles": [101, 102]}

    role1 = MagicMock(spec=discord.Role)
    role1.id = 101
    role2 = MagicMock(spec=discord.Role)
    role2.id = 102

    def side_effect(role_id: int) -> MagicMock | None:
        if role_id == 101:
            return role1
        if role_id == 102:
            return role2
        return None

    guild.get_role.side_effect = side_effect

    user.roles = []
    guild.default_role = MagicMock()

    user.edit = AsyncMock()
    actions.log_restoration = AsyncMock()  # type: ignore[method-assign]

    result = await actions.restore_user(guild, user)

    assert result is True
    user.edit.assert_called_once()
    args, kwargs = user.edit.call_args
    assert "roles" in kwargs
    assert len(kwargs["roles"]) == 2
    assert role1 in kwargs["roles"]
    assert role2 in kwargs["roles"]

    assert str(user.id) not in q_users_dict
