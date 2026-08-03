"""Shared fixtures for unicornimage tests."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config
from redbot.core.bot import Red

from unicornimage.unicornimage import UnicornImage


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.horde_api_key = AsyncMock(return_value="test-key")
    config.horde_api_key.set = AsyncMock()
    config.modal_app_name = AsyncMock(return_value="text2image")
    config.modal_app_name.set = AsyncMock()
    config.modal_prompt = AsyncMock(return_value="high quality")
    config.modal_prompt.set = AsyncMock()
    config.generation_limit = AsyncMock(return_value=1)
    config.generation_limit.set = AsyncMock()

    def _guild(*args: object, **kwargs: object) -> object:
        class _Group:
            premium_role_id = AsyncMock(return_value=None)

            def __getattr__(self, name: str) -> AsyncMock:
                am = AsyncMock(return_value=None)
                am.set = AsyncMock()
                return am

        return _Group()

    config.guild.side_effect = _guild
    return config


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.is_owner = AsyncMock(return_value=False)
    bot.owner_ids = set()
    bot.session = MagicMock()
    return bot


@pytest.fixture
def cog(bot_mock: MagicMock, config_mock: MagicMock) -> UnicornImage:
    with (
        patch("unicornimage.unicornimage.Config.get_conf", return_value=config_mock),
        patch("discord.ext.tasks.Loop.start"),
    ):
        instance = UnicornImage(bot_mock)  # type: ignore[arg-type]
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
