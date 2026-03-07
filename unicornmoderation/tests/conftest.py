"""Shared fixtures for unicornmoderation tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from unicornmoderation.unicorn_moderation import UnicornModeration

LOG_CHANNEL_ID = 694857480307474432
MUTED_ROLE_ID = 686252873583165520


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)

    def _member(*args: object, **kwargs: object) -> object:
        class _Group:
            warnings = AsyncMock(return_value=[])

            def __getattr__(self, name: str) -> AsyncMock:
                return AsyncMock(return_value=None)

        return _Group()

    config.member.side_effect = _member
    return config


@pytest.fixture
def log_channel_mock() -> MagicMock:
    ch = MagicMock(spec=["send", "id", "name"])
    ch.send = AsyncMock()
    return ch


@pytest.fixture
def bot_mock(log_channel_mock: MagicMock) -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.get_channel = MagicMock(return_value=log_channel_mock)
    bot.loop = MagicMock()
    bot.loop.run_in_executor = AsyncMock(return_value=MagicMock())
    return bot


@pytest.fixture
def cog(bot_mock: MagicMock, config_mock: MagicMock) -> UnicornModeration:
    with patch("unicornmoderation.unicorn_moderation.Config.get_conf", return_value=config_mock):
        instance = UnicornModeration(bot_mock)  # type: ignore[arg-type]
    instance.config = config_mock
    return instance
