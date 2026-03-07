"""Shared fixtures for unimod tests."""

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
    """Config mock with unimod guild defaults."""
    config = MagicMock(spec=Config)
    guild_data = {
        "enabled": True,
        "alert_channel_id": None,
        "whitelisted_channels": [],
        "vader_threshold": -0.5,
        "buffer_size": 20,
    }

    def _guild_side_effect(*args: object, **kwargs: object) -> object:
        class GuildGroup:
            def __getattr__(self, name: str) -> AsyncMock:
                if name in guild_data:
                    return AsyncMock(return_value=guild_data[name])
                return AsyncMock(return_value=None)

        return GuildGroup()

    config.guild.side_effect = _guild_side_effect
    return config


@pytest.fixture
def bot_mock() -> MagicMock:
    """Lightweight Red bot mock."""
    bot = MagicMock()
    bot.get_context = AsyncMock(return_value=MagicMock(valid=False))
    bot.get_shared_api_tokens = AsyncMock(return_value={"api_key": "test-key"})
    return bot


@pytest.fixture
def cog(bot_mock: MagicMock, config_mock: MagicMock) -> UniMod:
    """UniMod cog with mocked Config and suppressed task loop."""
    with (
        patch("unimod.unimod.Config.get_conf", return_value=config_mock),
        patch("discord.ext.tasks.Loop.start"),
    ):
        instance = UniMod(bot_mock)  # type: ignore[arg-type]
    instance.config = config_mock
    return instance


@pytest_asyncio.fixture
async def bot() -> AsyncGenerator[dpy_commands.Bot, None]:
    """dpytest-configured plain discord.py Bot."""
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    intents.message_content = True

    real_bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await real_bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(real_bot)

    yield real_bot

    await dpytest.empty_queue()
