"""Shared fixtures for tickets tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from tickets.common.constants import DEFAULT_GUILD


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.all_guilds = AsyncMock(return_value={})

    def _guild(*args: object, **kwargs: object) -> object:
        class _Group:
            async def all(self) -> dict:
                return dict(DEFAULT_GUILD)

            opened = AsyncMock(return_value={})

            def __getattr__(self, name: str) -> AsyncMock:
                am = AsyncMock(return_value=None)
                am.set = AsyncMock()
                return am

        return _Group()

    config.guild.side_effect = _guild
    config.register_guild = MagicMock()
    config.guild_from_id = MagicMock(return_value=MagicMock())
    return config


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.wait_until_red_ready = AsyncMock()
    bot.get_guild = MagicMock(return_value=None)
    bot.user = MagicMock(name="AutoClose")
    return bot
