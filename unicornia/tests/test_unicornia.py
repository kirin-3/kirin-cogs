"""Unit, async, and dpytest integration tests for the Unicornia cog."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config, commands
from redbot.core.bot import Red

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unicornia.errors import SystemNotReadyError, UnicorniaError
from unicornia.unicornia import Unicornia


def _make_config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.register_global = MagicMock()
    config.register_guild = MagicMock()
    config.nadeko_db_path = AsyncMock(return_value=None)
    config.generation_channels = AsyncMock(return_value=[])

    guild_group = MagicMock()
    guild_group.command_whitelist = AsyncMock(return_value={})
    guild_group.system_whitelist = AsyncMock(return_value={})
    config.guild = MagicMock(return_value=guild_group)
    return config


def _mark_systems_ready(
    cog: Unicornia,
    *,
    db: Any | None = None,
    xp_system: Any | None = None,
    economy_system: Any | None = None,
    currency_generation: Any | None = None,
    market_system: Any | None = None,
) -> None:
    cog.db = db or MagicMock()
    cog.xp_system = xp_system or MagicMock()
    cog.economy_system = economy_system or MagicMock()
    cog.gambling_system = MagicMock()
    cog.currency_generation = currency_generation or MagicMock()
    cog.currency_decay = MagicMock()
    cog.nitro_system = MagicMock()
    cog.market_system = market_system or MagicMock()


def _make_command(
    *,
    name: str,
    qualified_name: str,
    module_name: str,
    parent: Any | None = None,
    cog_name: str = "Unicornia",
) -> SimpleNamespace:
    callback = SimpleNamespace(__module__=module_name)
    return SimpleNamespace(
        name=name,
        qualified_name=qualified_name,
        callback=callback,
        parent=parent,
        cog_name=cog_name,
    )


def _make_ctx(*, command: Any, channel_id: int = 100, with_guild: bool = True) -> MagicMock:
    ctx = MagicMock(spec=commands.Context)
    ctx.command = command
    ctx.author = MagicMock(spec=discord.Member)
    ctx.guild = MagicMock(spec=discord.Guild) if with_guild else None
    ctx.channel = MagicMock(spec=discord.TextChannel)
    ctx.channel.id = channel_id
    ctx.send = AsyncMock()
    ctx.command_failed = True
    return ctx


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.is_owner = AsyncMock(return_value=False)
    bot.add_view = MagicMock()
    bot.wait_until_ready = AsyncMock()
    return bot


@pytest.fixture
def config_mock() -> MagicMock:
    return _make_config_mock()


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock, config_mock: MagicMock) -> Unicornia:
    with patch("unicornia.unicornia.Config.get_conf", return_value=config_mock):
        unicornia_cog = Unicornia(bot_mock)
    unicornia_cog.config = config_mock
    return unicornia_cog


@pytest.mark.asyncio
async def test_check_systems_ready_requires_all_systems(cog: Unicornia) -> None:
    assert cog._check_systems_ready() is False

    _mark_systems_ready(cog)

    assert cog._check_systems_ready() is True


@pytest.mark.asyncio
async def test_red_get_data_for_user_collects_available_sections(cog: Unicornia) -> None:
    db = MagicMock()
    db.xp.get_all_user_xp = AsyncMock(return_value=[(123, 10), (456, 20)])
    db.economy.get_user_currency = AsyncMock(return_value=500)
    db.economy.get_bank_user = AsyncMock(return_value={"balance": 2000})
    db.waifu.get_user_waifus = AsyncMock(return_value=[{"waifu_id": 1}])
    db.economy.get_currency_transactions = AsyncMock(return_value=[{"amount": 100}])
    _mark_systems_ready(cog, db=db)

    data = await cog.red_get_data_for_user(user_id=42)

    assert data["xp"] == [{"guild_id": 123, "xp": 10}, {"guild_id": 456, "xp": 20}]
    assert data["currency"] == 500
    assert data["bank"] == {"balance": 2000}
    assert data["waifus"] == [{"waifu_id": 1}]
    assert data["transactions"] == [{"amount": 100}]


@pytest.mark.asyncio
async def test_red_delete_data_for_user_calls_database_delete(cog: Unicornia) -> None:
    db = MagicMock()
    db.delete_user_data = AsyncMock()
    _mark_systems_ready(cog, db=db)

    await cog.red_delete_data_for_user(requester="user", user_id=99)

    db.delete_user_data.assert_awaited_once_with(99)


@pytest.mark.asyncio
async def test_get_balance_returns_fallback_when_not_ready(cog: Unicornia) -> None:
    wallet, bank = await cog.get_balance(1)
    assert (wallet, bank) == (0, 0)


@pytest.mark.asyncio
async def test_add_balance_passes_expected_transaction_metadata(cog: Unicornia) -> None:
    economy_system = MagicMock()
    economy_system.add_currency = AsyncMock(return_value=True)
    _mark_systems_ready(cog, economy_system=economy_system)

    result = await cog.add_balance(10, 250, reason="reward", source="ContestCog")

    assert result is True
    economy_system.add_currency.assert_awaited_once_with(
        10,
        250,
        transaction_type="api_add",
        extra="ContestCog",
        note="reward",
    )


@pytest.mark.asyncio
async def test_cog_check_raises_when_systems_not_ready(cog: Unicornia) -> None:
    command = _make_command(name="balance", qualified_name="balance", module_name="unicornia.commands.economy")
    ctx = _make_ctx(command=command)

    with pytest.raises(SystemNotReadyError):
        await cog.cog_check(ctx)


@pytest.mark.asyncio
async def test_cog_check_allows_bot_owner(cog: Unicornia, bot_mock: MagicMock) -> None:
    _mark_systems_ready(cog)
    bot_mock.is_owner = AsyncMock(return_value=True)
    command = _make_command(name="balance", qualified_name="balance", module_name="unicornia.commands.economy")
    ctx = _make_ctx(command=command)

    allowed = await cog.cog_check(ctx)

    assert allowed is True


@pytest.mark.asyncio
async def test_cog_check_allows_pick_in_generation_channel(cog: Unicornia, config_mock: MagicMock) -> None:
    _mark_systems_ready(cog)
    config_mock.generation_channels = AsyncMock(return_value=[777])
    command = _make_command(name="pick", qualified_name="pick", module_name="unicornia.commands.currency")
    ctx = _make_ctx(command=command, channel_id=777)

    allowed = await cog.cog_check(ctx)

    assert allowed is True


@pytest.mark.asyncio
async def test_cog_check_honors_parent_command_whitelist(cog: Unicornia, config_mock: MagicMock) -> None:
    _mark_systems_ready(cog)
    guild_group = config_mock.guild.return_value
    guild_group.command_whitelist = AsyncMock(return_value={"economy": [123]})
    guild_group.system_whitelist = AsyncMock(return_value={})

    parent = _make_command(name="economy", qualified_name="economy", module_name="unicornia.commands.economy")
    command = _make_command(
        name="balance",
        qualified_name="economy balance",
        module_name="unicornia.commands.economy",
        parent=parent,
    )
    ctx = _make_ctx(command=command, channel_id=123)

    allowed = await cog.cog_check(ctx)

    assert allowed is True


@pytest.mark.asyncio
async def test_cog_check_honors_system_whitelist(cog: Unicornia, config_mock: MagicMock) -> None:
    _mark_systems_ready(cog)
    guild_group = config_mock.guild.return_value
    guild_group.command_whitelist = AsyncMock(return_value={})
    guild_group.system_whitelist = AsyncMock(return_value={"economy": [400]})

    command = _make_command(name="balance", qualified_name="balance", module_name="unicornia.commands.economy")
    ctx = _make_ctx(command=command, channel_id=401)

    allowed = await cog.cog_check(ctx)

    assert allowed is False


@pytest.mark.asyncio
async def test_on_command_error_handles_unicornia_error(cog: Unicornia) -> None:
    command = _make_command(
        name="balance",
        qualified_name="balance",
        module_name="unicornia.commands.economy",
        cog_name=cog.qualified_name,
    )
    ctx = _make_ctx(command=command)

    await cog.on_command_error(ctx, UnicorniaError("failed gracefully"))

    ctx.send.assert_awaited_once_with("failed gracefully")
    assert ctx.command_failed is False


@pytest.mark.asyncio
async def test_on_message_processes_all_message_systems_when_ready(cog: Unicornia) -> None:
    xp_system = MagicMock()
    xp_system.process_message = AsyncMock()
    currency_generation = MagicMock()
    currency_generation.process_message = AsyncMock()
    market_system = MagicMock()
    market_system.process_message = AsyncMock()

    _mark_systems_ready(
        cog,
        xp_system=xp_system,
        currency_generation=currency_generation,
        market_system=market_system,
    )

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = False
    message.guild = MagicMock(spec=discord.Guild)

    await cog.on_message(message)

    xp_system.process_message.assert_awaited_once_with(message)
    currency_generation.process_message.assert_awaited_once_with(message)
    market_system.process_message.assert_awaited_once_with(message)


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
async def test_dpytest_message_dispatches_unicornia_listener(dpytest_bot: dpy_commands.Bot) -> None:
    config_mock = _make_config_mock()

    with patch("unicornia.unicornia.Config.get_conf", return_value=config_mock):
        cog = Unicornia(dpytest_bot)  # type: ignore[arg-type]

    # Prevent heavy DB/system initialization during add_cog.
    cog.cog_load = AsyncMock()  # type: ignore[method-assign]

    xp_system = MagicMock()
    xp_system.process_message = AsyncMock()
    currency_generation = MagicMock()
    currency_generation.process_message = AsyncMock()
    market_system = MagicMock()
    market_system.process_message = AsyncMock()
    _mark_systems_ready(
        cog,
        xp_system=xp_system,
        currency_generation=currency_generation,
        market_system=market_system,
    )

    await dpytest_bot.add_cog(cog)

    await dpytest.message("hello unicornia")
    await dpytest.run_all_events()
    await dpytest.empty_queue()

    cast(AsyncMock, xp_system.process_message).assert_awaited_once()
    cast(AsyncMock, currency_generation.process_message).assert_awaited_once()
    cast(AsyncMock, market_system.process_message).assert_awaited_once()


@pytest.mark.asyncio
async def test_dpytest_balance_command_raises_when_systems_not_ready(dpytest_bot: dpy_commands.Bot) -> None:
    config_mock = _make_config_mock()

    with patch("unicornia.unicornia.Config.get_conf", return_value=config_mock):
        cog = Unicornia(dpytest_bot)  # type: ignore[arg-type]

    # Prevent heavy DB/system initialization during add_cog.
    cog.cog_load = AsyncMock()  # type: ignore[method-assign]
    await dpytest_bot.add_cog(cog)

    with pytest.raises(SystemNotReadyError, match="Systems are still initializing"):
        await dpytest.message("!balance")
