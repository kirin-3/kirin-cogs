"""Unit and dpytest integration tests for the RulesAccept cog."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config

from rulesaccept.rulesaccept import RulesAccept, rulesacceptButton, rulesacceptModal, rulesacceptView


def _make_config_attr(value: object) -> AsyncMock:
    attr = AsyncMock(return_value=value)
    attr.set = AsyncMock()
    return attr


def _make_config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.register_guild = MagicMock()

    guild_group = MagicMock()
    guild_group.rules_channel_id = _make_config_attr(684360255798509582)
    guild_group.member_role_id = _make_config_attr(686098839651876908)

    config.guild = MagicMock(return_value=guild_group)
    return config


def _make_interaction(*, member: MagicMock, guild: discord.Guild | None) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = member
    interaction.guild = guild
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _manageable_role(role_id: int = 42) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.managed = False
    role.is_default.return_value = False
    role.__ge__.return_value = False
    return role


def _configure_role_permissions(guild: MagicMock) -> None:
    guild.me = MagicMock(spec=discord.Member)
    guild.me.guild_permissions.manage_roles = True
    guild.me.top_role = MagicMock(spec=discord.Role)


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock()
    bot.add_view = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    return bot


@pytest.fixture
def config_mock() -> MagicMock:
    return _make_config_mock()


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock, config_mock: MagicMock) -> RulesAccept:
    with patch("rulesaccept.rulesaccept.Config.get_conf", return_value=config_mock):
        rules_cog = RulesAccept(bot_mock)
    rules_cog.config = config_mock
    return rules_cog


@pytest.mark.asyncio
async def test_cog_load_adds_persistent_view(cog: RulesAccept, bot_mock: MagicMock) -> None:
    await cog.cog_load()

    bot_mock.add_view.assert_called_once()
    view = bot_mock.add_view.call_args[0][0]
    assert isinstance(view, rulesacceptView)


@pytest.mark.asyncio
async def test_sendrules_sends_message_with_view(cog: RulesAccept) -> None:
    ctx = MagicMock()
    ctx.send = AsyncMock()

    await cog.sendrules.callback(cog, ctx)  # type: ignore[arg-type]

    ctx.send.assert_awaited_once()
    text = ctx.send.call_args[0][0]
    view = ctx.send.call_args[1]["view"]
    assert "Please read the rules" in text
    assert isinstance(view, rulesacceptView)


@pytest.mark.asyncio
async def test_setrole_updates_config(cog: RulesAccept, config_mock: MagicMock) -> None:
    ctx = MagicMock()
    ctx.guild = MagicMock(spec=discord.Guild)
    ctx.send = AsyncMock()

    role = _manageable_role()
    role.name = "Members"

    await cog.setrole.callback(cog, ctx, role)  # type: ignore[arg-type]

    config_mock.guild.return_value.member_role_id.set.assert_awaited_once_with(42)
    ctx.send.assert_awaited_once_with("Role set to Members.")


@pytest.mark.asyncio
async def test_button_callback_opens_modal(cog: RulesAccept) -> None:
    button = rulesacceptButton(cog)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.send_modal = AsyncMock()

    await button.callback(interaction)

    interaction.response.send_modal.assert_awaited_once()
    modal = interaction.response.send_modal.call_args[0][0]
    assert isinstance(modal, rulesacceptModal)


@pytest.mark.asyncio
async def test_modal_submit_invalid_response(cog: RulesAccept, bot_mock: MagicMock) -> None:
    modal = rulesacceptModal(cog)
    modal.answer._value = "I do not agree"

    member = MagicMock(spec=discord.Member)
    member.id = 100
    member.mention = "<@100>"

    guild = MagicMock(spec=discord.Guild)
    interaction = _make_interaction(member=member, guild=guild)
    bot_mock.get_channel.return_value = None

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_awaited_once_with(
        "You must type exactly: I agree to the rules.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_modal_submit_valid_assigns_role_and_sends_followup(cog: RulesAccept, config_mock: MagicMock) -> None:
    modal = rulesacceptModal(cog)
    modal.answer._value = "I agree to the rules."

    role = _manageable_role()

    guild = MagicMock(spec=discord.Guild)
    _configure_role_permissions(guild)
    guild.get_role.return_value = role

    member = MagicMock(spec=discord.Member)
    member.id = 555
    member.mention = "<@555>"
    member.add_roles = AsyncMock()

    interaction = _make_interaction(member=member, guild=guild)

    log_channel = MagicMock(spec=discord.TextChannel)
    log_channel.send = AsyncMock()
    cog.bot.get_channel = MagicMock(return_value=log_channel)

    config_mock.guild.return_value.member_role_id = AsyncMock(return_value=42)

    await modal.on_submit(interaction)

    log_channel.send.assert_awaited_once()
    member.add_roles.assert_awaited_once_with(role, reason="Accepted the rules.")
    interaction.response.send_message.assert_awaited_once_with(
        "Thank you! You have accepted the rules and have been given access.", ephemeral=True
    )
    interaction.followup.send.assert_awaited_once_with(
        "You will need a role from <#708066544688562196> channel as well for full access.",
        ephemeral=True,
    )


@pytest.mark.asyncio
async def test_modal_submit_valid_role_missing(cog: RulesAccept, config_mock: MagicMock) -> None:
    modal = rulesacceptModal(cog)
    modal.answer._value = "I agree to the rules."

    guild = MagicMock(spec=discord.Guild)
    guild.get_role.return_value = None

    member = MagicMock(spec=discord.Member)
    member.id = 777
    member.mention = "<@777>"

    interaction = _make_interaction(member=member, guild=guild)
    config_mock.guild.return_value.member_role_id = AsyncMock(return_value=999)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_awaited_once_with(
        "Role not found. Please contact an admin.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_modal_submit_valid_role_assign_error(cog: RulesAccept, config_mock: MagicMock) -> None:
    modal = rulesacceptModal(cog)
    modal.answer._value = "I Agree To The Rules."

    role = _manageable_role()

    guild = MagicMock(spec=discord.Guild)
    _configure_role_permissions(guild)
    guild.get_role.return_value = role

    member = MagicMock(spec=discord.Member)
    member.id = 888
    member.mention = "<@888>"
    member.add_roles = AsyncMock(side_effect=RuntimeError("failed"))

    interaction = _make_interaction(member=member, guild=guild)
    config_mock.guild.return_value.member_role_id = AsyncMock(return_value=42)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_awaited_once_with(
        "The role could not be assigned. Please contact an administrator.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_modal_submit_valid_with_no_guild_returns_silently(cog: RulesAccept) -> None:
    modal = rulesacceptModal(cog)
    modal.answer._value = "I agree to the rules."

    member = MagicMock(spec=discord.Member)
    member.id = 999
    member.mention = "<@999>"

    interaction = _make_interaction(member=member, guild=None)

    await modal.on_submit(interaction)

    interaction.response.send_message.assert_awaited_once_with(
        "This action can only be performed in a server.", ephemeral=True
    )
    interaction.followup.send.assert_not_called()


@pytest_asyncio.fixture
async def dpytest_bot() -> AsyncGenerator[dpy_commands.Bot, None]:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    intents.messages = True
    intents.message_content = True

    bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(bot)

    yield bot

    await dpytest.empty_queue()


@pytest.mark.asyncio
async def test_dpytest_sendrules_callback_uses_real_guild_context(dpytest_bot: dpy_commands.Bot) -> None:
    config_mock = _make_config_mock()

    with patch("rulesaccept.rulesaccept.Config.get_conf", return_value=config_mock):
        cog = RulesAccept(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock
    await dpytest_bot.add_cog(cog)

    ctx = MagicMock()
    ctx.guild = dpytest.get_config().guilds[0]
    ctx.send = AsyncMock()

    await cog.sendrules.callback(cog, ctx)  # type: ignore[arg-type]

    ctx.send.assert_awaited_once()
    assert "Please read the rules" in ctx.send.call_args[0][0]
    assert isinstance(ctx.send.call_args[1]["view"], rulesacceptView)
