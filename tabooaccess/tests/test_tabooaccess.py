"""Tests for the TabooAccess cog."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio
from redbot.core import Config
from redbot.core.bot import Red
from redbot.core.commands import Context

from tabooaccess.tabooaccess import LetMeInButton, LetMeOutButton, TabooAccess, TabooAccessModal, TabooAccessView


def _manageable_role(role_id: int = 123456789) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.managed = False
    role.is_default.return_value = False
    role.__ge__.return_value = False
    return role


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.add_view = MagicMock()
    return bot


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)

    # Setup chain: config.guild(guild).taboo_role_id() and config.guild(guild).taboo_role_id.set()
    guild_group = MagicMock()
    guild_group.taboo_role_id = AsyncMock(return_value=123456789)
    guild_group.taboo_role_id.set = AsyncMock()

    config.guild = MagicMock(return_value=guild_group)
    return config


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock, config_mock: MagicMock) -> TabooAccess:
    with patch("tabooaccess.tabooaccess.Config.get_conf", return_value=config_mock):
        c = TabooAccess(bot_mock)
    c.config = config_mock
    return c


@pytest.fixture
def ctx_mock() -> Context:
    ctx = MagicMock(spec=Context)
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.send = AsyncMock()
    return ctx


@pytest.fixture
def interaction_mock() -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_modal = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.me = MagicMock(spec=discord.Member)
    interaction.guild.me.guild_permissions.manage_roles = True
    interaction.guild.me.top_role = MagicMock(spec=discord.Role)
    interaction.user = MagicMock(spec=discord.Member)
    return interaction


# --- Cog Tests ---


@pytest.mark.asyncio
async def test_cog_load(cog: TabooAccess, bot_mock: MagicMock) -> None:
    await cog.cog_load()
    bot_mock.add_view.assert_called_once()
    assert isinstance(bot_mock.add_view.call_args[0][0], TabooAccessView)


@pytest.mark.asyncio
async def test_sendtaboo(cog: TabooAccess, ctx_mock: MagicMock) -> None:
    await getattr(cog.sendtaboo, "callback")(cog, ctx_mock)  # noqa: B009

    ctx_mock.send.assert_called_once()
    args, kwargs = ctx_mock.send.call_args
    assert "Click the button below" in args[0]
    assert "view" in kwargs
    assert isinstance(kwargs["view"], TabooAccessView)


@pytest.mark.asyncio
async def test_settaboorole(cog: TabooAccess, ctx_mock: MagicMock, config_mock: MagicMock) -> None:
    role = MagicMock(spec=discord.Role)
    role.id = 987654321
    role.name = "TestTabooRole"

    await getattr(cog.settaboorole, "callback")(cog, ctx_mock, role)  # noqa: B009

    guild_group = config_mock.guild(ctx_mock.guild)
    guild_group.taboo_role_id.set.assert_called_once_with(987654321)

    ctx_mock.send.assert_called_once_with("Taboo access role set to TestTabooRole.")


# --- View & Button Tests ---


@pytest.mark.asyncio
async def test_let_me_in_button_callback(cog: TabooAccess, interaction_mock: MagicMock) -> None:
    button = LetMeInButton(cog)

    await button.callback(interaction_mock)

    interaction_mock.response.send_modal.assert_called_once()
    args, _kwargs = interaction_mock.response.send_modal.call_args
    assert isinstance(args[0], TabooAccessModal)


@pytest.mark.asyncio
async def test_let_me_out_button_callback_success(
    cog: TabooAccess, interaction_mock: MagicMock, config_mock: MagicMock
) -> None:
    role = _manageable_role()
    interaction_mock.user.roles = [role]
    interaction_mock.user.remove_roles = AsyncMock()

    interaction_mock.guild.get_role.return_value = role

    button = LetMeOutButton(cog)
    await button.callback(interaction_mock)

    interaction_mock.user.remove_roles.assert_called_once_with(role, reason="Removed taboo access.")
    interaction_mock.response.send_message.assert_called_once_with(
        "You have been removed from taboo content access.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_let_me_out_button_callback_no_role(
    cog: TabooAccess, interaction_mock: MagicMock, config_mock: MagicMock
) -> None:
    role = _manageable_role()
    interaction_mock.user.roles = []  # User doesn't have the role
    interaction_mock.guild.get_role.return_value = role

    button = LetMeOutButton(cog)
    await button.callback(interaction_mock)

    interaction_mock.response.send_message.assert_called_once_with(
        "You don't have the taboo access role.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_let_me_out_button_callback_exception(
    cog: TabooAccess, interaction_mock: MagicMock, config_mock: MagicMock
) -> None:
    role = _manageable_role()
    interaction_mock.user.roles = [role]
    error = discord.Forbidden(MagicMock(), "no perms")
    interaction_mock.user.remove_roles = AsyncMock(side_effect=error)
    interaction_mock.guild.get_role.return_value = role

    button = LetMeOutButton(cog)
    await button.callback(interaction_mock)

    interaction_mock.response.send_message.assert_called_once_with(
        "I do not have permission to remove this role.", ephemeral=True
    )


# --- Modal Tests ---


@pytest.mark.parametrize("valid_answer", ["yes", "YES", "i agree", "  I AGREE  "])
@pytest.mark.asyncio
async def test_taboo_access_modal_on_submit_success(
    cog: TabooAccess, interaction_mock: MagicMock, valid_answer: str
) -> None:
    modal = TabooAccessModal(cog)
    modal.answer = MagicMock()
    modal.answer.value = valid_answer

    role = _manageable_role()
    interaction_mock.guild.get_role.return_value = role
    interaction_mock.user.add_roles = AsyncMock()

    await modal.on_submit(interaction_mock)

    interaction_mock.user.add_roles.assert_called_once_with(role, reason="Accepted taboo access.")
    interaction_mock.response.send_message.assert_called_once_with(
        "Thank you! You have been granted taboo content access.", ephemeral=True
    )


@pytest.mark.parametrize("invalid_answer", ["no", "idk", "what", ""])
@pytest.mark.asyncio
async def test_taboo_access_modal_on_submit_invalid(
    cog: TabooAccess, interaction_mock: MagicMock, invalid_answer: str
) -> None:
    modal = TabooAccessModal(cog)
    modal.answer = MagicMock()
    modal.answer.value = invalid_answer

    await modal.on_submit(interaction_mock)

    interaction_mock.response.send_message.assert_called_once_with(
        "You must type 'yes' or 'i agree' to confirm.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_taboo_access_modal_on_submit_role_not_found(cog: TabooAccess, interaction_mock: MagicMock) -> None:
    modal = TabooAccessModal(cog)
    modal.answer = MagicMock()
    modal.answer.value = "yes"

    # Simulate role not found by returning None
    interaction_mock.guild.get_role.return_value = None

    await modal.on_submit(interaction_mock)

    interaction_mock.response.send_message.assert_called_once_with(
        "Role not found. Please contact an admin.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_taboo_access_modal_on_submit_exception(cog: TabooAccess, interaction_mock: MagicMock) -> None:
    modal = TabooAccessModal(cog)
    modal.answer = MagicMock()
    modal.answer.value = "yes"

    role = _manageable_role()
    interaction_mock.guild.get_role.return_value = role

    error = discord.Forbidden(MagicMock(), "no perms")
    interaction_mock.user.add_roles = AsyncMock(side_effect=error)

    await modal.on_submit(interaction_mock)

    interaction_mock.response.send_message.assert_called_once_with(
        "I do not have permission to assign this role.", ephemeral=True
    )
