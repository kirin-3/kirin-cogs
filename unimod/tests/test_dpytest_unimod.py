"""dpytest integration tests for unimod - on_message flow and config commands."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config

from unimod.unimod import UniMod


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    guild_data: dict[str, object] = {
        "enabled": True,
        "alert_channel_id": None,
        "whitelisted_channels": [],
        "vader_threshold": -0.5,
        "buffer_size": 20,
    }

    def _guild(*args: object, **kwargs: object) -> object:
        class _Group:
            whitelisted_channels = AsyncMock(return_value=guild_data["whitelisted_channels"])

            def __getattr__(self, name: str) -> AsyncMock:
                if name in guild_data:
                    val = guild_data[name]
                    mock = AsyncMock(return_value=val)
                    mock.set = AsyncMock()
                    return mock
                am = AsyncMock(return_value=None)
                am.set = AsyncMock()
                return am

        return _Group()

    config.guild.side_effect = _guild
    return config


@pytest_asyncio.fixture
async def bot_and_cog(
    config_mock: MagicMock,
) -> AsyncGenerator[tuple[dpy_commands.Bot, UniMod], None]:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    intents.message_content = True

    real_bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    real_bot.owner_id = 1
    await real_bot._async_setup_hook()  # type: ignore[attr-defined]

    with (
        patch("unimod.unimod.Config.get_conf", return_value=config_mock),
        patch("discord.ext.tasks.Loop.start"),
    ):
        cog = UniMod(real_bot)  # type: ignore[arg-type]
    cog.config = config_mock

    dpytest.configure(real_bot)
    await real_bot.add_cog(cog)

    yield real_bot, cog

    await dpytest.empty_queue()


# --- on_message: bot filter ---


@pytest.mark.asyncio
async def test_on_message_ignores_bot(bot_and_cog: tuple[dpy_commands.Bot, UniMod]) -> None:
    """Messages from bots are ignored."""
    _, cog = bot_and_cog
    initial_processed = cog.stats["messages_processed"]

    # Send message from a bot (dpytest test user is not a bot, so send manually via dispatch)
    guild = dpytest.get_config().guilds[0]
    channel = dpytest.get_config().channels[0]
    bot_user = dpytest.back.make_user("FakeBot", "0001")
    bot_user.bot = True  # type: ignore[misc]
    member = dpytest.back.make_member(bot_user, guild)

    msg = dpytest.back.make_message("hello", member, channel)
    bot_and_cog[0].dispatch("message", msg)
    await dpytest.run_all_events()

    # Should NOT have incremented
    assert cog.stats["messages_processed"] == initial_processed


@pytest.mark.asyncio
async def test_on_message_ignores_non_whitelisted(bot_and_cog: tuple[dpy_commands.Bot, UniMod]) -> None:
    """Messages in non-whitelisted channels are ignored."""
    _, cog = bot_and_cog
    # whitelisted_channels returns [] by default
    initial_processed = cog.stats["messages_processed"]

    await dpytest.message("hello from a user")
    await dpytest.run_all_events()

    # Not whitelisted → not counted
    assert cog.stats["messages_processed"] == initial_processed


@pytest.mark.asyncio
async def test_on_message_buffered_when_whitelisted(bot_and_cog: tuple[dpy_commands.Bot, UniMod]) -> None:
    """Messages in whitelisted channels are buffered."""
    _real_bot, cog = bot_and_cog
    channel = dpytest.get_config().channels[0]

    # Reconfigure guild config mock to return whitelisted channel
    guild_data: dict[str, object] = {
        "enabled": True,
        "alert_channel_id": None,
        "whitelisted_channels": [channel.id],
        "vader_threshold": -0.5,
        "buffer_size": 20,
    }

    def _guild(*args: object, **kwargs: object) -> object:
        class _Group:
            def __getattr__(self, name: str) -> AsyncMock:
                val = guild_data.get(name)
                am = AsyncMock(return_value=val)
                am.set = AsyncMock()
                return am

        return _Group()

    cog.config.guild.side_effect = _guild  # pyright: ignore[reportAttributeAccessIssue]

    await dpytest.message("hello from a user")
    await dpytest.run_all_events()

    # Even if no pending tasks the message should have been processed (stats incremented)
    assert cog.stats["messages_processed"] >= 1


# --- toggle command (direct invocation, bypasses is_owner check) ---


@pytest.mark.asyncio
async def test_toggle_command_sends_response(bot_and_cog: tuple[dpy_commands.Bot, UniMod]) -> None:
    """unimod toggle sends 'enabled' or 'disabled' message when invoked directly."""
    _, cog = bot_and_cog

    guild = dpytest.get_config().guilds[0]

    ctx = MagicMock()
    ctx.guild = guild
    ctx.send = AsyncMock()

    # Call the underlying async handler directly (skips permission decorators)
    await cog.toggle_monitoring(ctx)  # type: ignore[arg-type]

    ctx.send.assert_called_once()
    sent_text: str = ctx.send.call_args[0][0]
    assert "UniMod monitoring" in sent_text
    assert "enabled" in sent_text or "disabled" in sent_text


@pytest.mark.asyncio
async def test_whitelist_command_adds_channel(bot_and_cog: tuple[dpy_commands.Bot, UniMod]) -> None:
    """whitelist_channels adds a channel and reports back."""
    _, cog = bot_and_cog

    guild = dpytest.get_config().guilds[0]
    channel = dpytest.get_config().channels[0]

    ctx = MagicMock()
    ctx.guild = guild
    ctx.send = AsyncMock()

    await cog.whitelist_channels(ctx, channel)  # type: ignore[arg-type]

    ctx.send.assert_called_once()
    sent_text: str = ctx.send.call_args[0][0]
    assert "Added to whitelist" in sent_text or "already whitelisted" in sent_text
