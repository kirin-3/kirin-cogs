"""Shared fixtures for unicornsecurity tests."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config

from unicornsecurity.imagefilter import ImageFilter

TARGET_CHANNEL_ID = 1319688029530492948


@pytest.fixture
def config_mock() -> MagicMock:
    """Config mock targeting target_channel_id."""
    config = MagicMock(spec=Config)

    def _guild(*args: object, **kwargs: object) -> object:
        class _Group:
            def __getattr__(self, name: str) -> AsyncMock:
                if name == "target_channel_id":
                    am = AsyncMock(return_value=TARGET_CHANNEL_ID)
                    am.set = AsyncMock()
                    return am
                am = AsyncMock(return_value=None)
                am.set = AsyncMock()
                return am

        return _Group()

    config.guild.side_effect = _guild
    return config


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    return bot


@pytest.fixture
def cog(bot_mock: MagicMock, config_mock: MagicMock) -> ImageFilter:
    with patch("unicornsecurity.imagefilter.Config.get_conf", return_value=config_mock):
        instance = ImageFilter(bot_mock)
    instance.config = config_mock
    return instance


@pytest_asyncio.fixture
async def bot() -> AsyncGenerator[dpy_commands.Bot, None]:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    intents.message_content = True

    real_bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await real_bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(real_bot)

    yield real_bot

    await dpytest.empty_queue()
