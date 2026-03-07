"""Fixtures for COTM tests."""
from unittest.mock import MagicMock

import pytest
from redbot.core.bot import Red

@pytest.fixture
def bot_mock():
    bot = MagicMock(spec=Red)
    bot.owner_ids = {111}
    bot.add_view = MagicMock()
    return bot
