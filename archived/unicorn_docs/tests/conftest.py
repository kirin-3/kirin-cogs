"""Shared fixtures for unicorn_docs tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from unicorn_docs.unicorndocs_precomputed import UnicornDocsPrecomputed


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.openrouter_api_key = AsyncMock(return_value="test-key")
    config.openrouter_api_key.set = AsyncMock()
    config.register_global = MagicMock()
    return config


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.session = MagicMock()
    return bot


@pytest.fixture
def cog(bot_mock: MagicMock, config_mock: MagicMock) -> UnicornDocsPrecomputed:
    with patch("unicorn_docs.unicorndocs_precomputed.Config.get_conf", return_value=config_mock):
        instance = UnicornDocsPrecomputed(bot_mock)  # type: ignore[arg-type]
    instance.config = config_mock
    return instance
