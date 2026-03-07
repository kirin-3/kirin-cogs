"""Tests for the VerifyUser cog."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import pytest_asyncio
from redbot.core.bot import Red
from redbot.core.commands import Context

from verifyuser.verifyuser import VerifyUser

# Role constants from the cog
AUTHORIZED_ROLE_ID = 898586656842600549
VERIFICATION_ROLE_ID = 1267157222530748439


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    return bot


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock) -> VerifyUser:
    return VerifyUser(bot_mock)


@pytest.fixture
def ctx_mock() -> Context:
    ctx = MagicMock(spec=Context)
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.author = MagicMock(spec=discord.Member)
    ctx.guild.me = MagicMock(spec=discord.Member)
    ctx.send = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_verifyuser_no_authorized_role(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    # Setup: The authorized role doesn't exist in the guild at all
    ctx_mock.guild.get_role.return_value = None

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.guild.get_role.assert_called_once_with(AUTHORIZED_ROLE_ID)
    ctx_mock.send.assert_called_once_with("You don't have permission to use this command.")


@pytest.mark.asyncio
async def test_verifyuser_author_missing_authorized_role(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    # Setup: The authorized role exists, but author doesn't have it
    authorized_role = MagicMock(spec=discord.Role)
    ctx_mock.guild.get_role.return_value = authorized_role
    ctx_mock.author.roles = []

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.send.assert_called_once_with("You don't have permission to use this command.")


@pytest.mark.asyncio
async def test_verifyuser_verification_role_missing(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    # Setup: Author has authorized role, but verification role doesn't exist
    authorized_role = MagicMock(spec=discord.Role)
    ctx_mock.author.roles = [authorized_role]

    def mock_get_role(role_id):
        if role_id == AUTHORIZED_ROLE_ID:
            return authorized_role
        if role_id == VERIFICATION_ROLE_ID:
            return None
        return None

    ctx_mock.guild.get_role.side_effect = mock_get_role

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.send.assert_called_once_with("The verification role could not be found.")


@pytest.mark.asyncio
async def test_verifyuser_target_not_found(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    # Setup roles correctly
    authorized_role = MagicMock(spec=discord.Role)
    verification_role = MagicMock(spec=discord.Role)
    ctx_mock.author.roles = [authorized_role]

    def mock_get_role(role_id):
        if role_id == AUTHORIZED_ROLE_ID:
            return authorized_role
        if role_id == VERIFICATION_ROLE_ID:
            return verification_role
        return None

    ctx_mock.guild.get_role.side_effect = mock_get_role

    # Target fetch fails with NotFound
    ctx_mock.guild.fetch_member.side_effect = discord.NotFound(MagicMock(), "not found")

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.send.assert_called_once_with("User with ID `12345` not found in this server.")


@pytest.mark.asyncio
async def test_verifyuser_fetch_http_exception(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    authorized_role = MagicMock(spec=discord.Role)
    verification_role = MagicMock(spec=discord.Role)
    ctx_mock.author.roles = [authorized_role]

    def mock_get_role(role_id):
        if role_id == AUTHORIZED_ROLE_ID:
            return authorized_role
        if role_id == VERIFICATION_ROLE_ID:
            return verification_role
        return None

    ctx_mock.guild.get_role.side_effect = mock_get_role

    # Target fetch fails with HTTPException
    ctx_mock.guild.fetch_member.side_effect = discord.HTTPException(MagicMock(), "http fail")

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.send.assert_called_once_with("An error occurred while fetching the user.")


@pytest.mark.asyncio
async def test_verifyuser_target_already_verified(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    authorized_role = MagicMock(spec=discord.Role)
    verification_role = MagicMock(spec=discord.Role)
    ctx_mock.author.roles = [authorized_role]

    def mock_get_role(role_id):
        if role_id == AUTHORIZED_ROLE_ID:
            return authorized_role
        if role_id == VERIFICATION_ROLE_ID:
            return verification_role
        return None

    ctx_mock.guild.get_role.side_effect = mock_get_role

    target_user = MagicMock(spec=discord.Member)
    target_user.roles = [verification_role]
    target_user.mention = "@user"
    ctx_mock.guild.fetch_member.return_value = target_user

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.send.assert_called_once_with("@user is already verified.")


@pytest.mark.asyncio
async def test_verifyuser_role_hierarchy_error(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    authorized_role = MagicMock(spec=discord.Role)
    verification_role = MagicMock(spec=discord.Role)

    # Roles are compared. The test simulates verification_role is higher than bot's top role
    verification_role.__ge__ = MagicMock(return_value=True)

    ctx_mock.author.roles = [authorized_role]

    def mock_get_role(role_id):
        if role_id == AUTHORIZED_ROLE_ID:
            return authorized_role
        if role_id == VERIFICATION_ROLE_ID:
            return verification_role
        return None

    ctx_mock.guild.get_role.side_effect = mock_get_role

    target_user = MagicMock(spec=discord.Member)
    target_user.roles = []
    target_user.mention = "@user"
    ctx_mock.guild.fetch_member.return_value = target_user

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.send.assert_called_once_with("I can't assign that role (it's higher than my top role).")


@pytest.mark.asyncio
async def test_verifyuser_success(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    authorized_role = MagicMock(spec=discord.Role)
    verification_role = MagicMock(spec=discord.Role)

    # Needs to be lower than bot's top role
    verification_role.__ge__ = MagicMock(return_value=False)

    ctx_mock.author.roles = [authorized_role]

    def mock_get_role(role_id):
        if role_id == AUTHORIZED_ROLE_ID:
            return authorized_role
        if role_id == VERIFICATION_ROLE_ID:
            return verification_role
        return None

    ctx_mock.guild.get_role.side_effect = mock_get_role

    target_user = MagicMock(spec=discord.Member)
    target_user.roles = []
    target_user.mention = "@user"
    target_user.add_roles = AsyncMock()
    ctx_mock.guild.fetch_member.return_value = target_user
    ctx_mock.author.__str__ = MagicMock(return_value="AdminUser#1234")

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    target_user.add_roles.assert_called_once_with(verification_role, reason="Verified by AdminUser#1234")
    ctx_mock.send.assert_called_once_with("Successfully verified @user!")


@pytest.mark.asyncio
async def test_verifyuser_add_roles_forbidden(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    authorized_role = MagicMock(spec=discord.Role)
    verification_role = MagicMock(spec=discord.Role)
    verification_role.__ge__ = MagicMock(return_value=False)

    ctx_mock.author.roles = [authorized_role]

    def mock_get_role(role_id):
        if role_id == AUTHORIZED_ROLE_ID:
            return authorized_role
        if role_id == VERIFICATION_ROLE_ID:
            return verification_role
        return None

    ctx_mock.guild.get_role.side_effect = mock_get_role

    target_user = MagicMock(spec=discord.Member)
    target_user.roles = []
    target_user.add_roles.side_effect = discord.Forbidden(MagicMock(), "no perms")
    ctx_mock.guild.fetch_member.return_value = target_user

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.send.assert_called_once_with("I don't have permission to assign roles.")


@pytest.mark.asyncio
async def test_verifyuser_add_roles_http_exception(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    authorized_role = MagicMock(spec=discord.Role)
    verification_role = MagicMock(spec=discord.Role)
    verification_role.__ge__ = MagicMock(return_value=False)

    ctx_mock.author.roles = [authorized_role]

    def mock_get_role(role_id):
        if role_id == AUTHORIZED_ROLE_ID:
            return authorized_role
        if role_id == VERIFICATION_ROLE_ID:
            return verification_role
        return None

    ctx_mock.guild.get_role.side_effect = mock_get_role

    target_user = MagicMock(spec=discord.Member)
    target_user.roles = []
    http_error = discord.HTTPException(MagicMock(), "intermittent error")
    target_user.add_roles.side_effect = http_error
    ctx_mock.guild.fetch_member.return_value = target_user

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.send.assert_called_once_with(f"An error occurred while assigning the role: {http_error}")


@pytest.mark.asyncio
async def test_verifyuser_add_roles_generic_exception(cog: VerifyUser, ctx_mock: MagicMock) -> None:
    authorized_role = MagicMock(spec=discord.Role)
    verification_role = MagicMock(spec=discord.Role)
    verification_role.__ge__ = MagicMock(return_value=False)

    ctx_mock.author.roles = [authorized_role]

    def mock_get_role(role_id):
        if role_id == AUTHORIZED_ROLE_ID:
            return authorized_role
        if role_id == VERIFICATION_ROLE_ID:
            return verification_role
        return None

    ctx_mock.guild.get_role.side_effect = mock_get_role

    target_user = MagicMock(spec=discord.Member)
    target_user.roles = []
    error = Exception("db crash")
    target_user.add_roles.side_effect = error
    ctx_mock.guild.fetch_member.return_value = target_user

    await getattr(cog.verifyuser, "callback")(cog, ctx_mock, 12345)  # noqa: B009

    ctx_mock.send.assert_called_once_with(f"An unexpected error occurred: {error}")
