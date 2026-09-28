"""Tests for the AdvancedUptime cog."""

from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from advanceduptime.advanceduptime import AdvancedUptime, unit_breakdown


def test_unit_breakdown_pluralises() -> None:
    assert unit_breakdown(timedelta(days=1, seconds=1)) == "+ 86,401 seconds\n+ 1,440 minutes\n+ 24 hours\n+ 1 day"


def test_config_matches_original_cog() -> None:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = AdvancedUptime(MagicMock())
    assert (cog.config.cog_name, cog.config.unique_identifier) == ("AdvancedUptime", "4589035903485")


@pytest.mark.asyncio
async def test_swaps_core_uptime_and_restores_it() -> None:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = AdvancedUptime(MagicMock())
    bot = cast(MagicMock, cog.bot)
    core = MagicMock()
    bot.remove_command.return_value = core
    await cog.cog_load()
    bot.remove_command.assert_called_once_with("uptime")
    await cog.cog_unload()
    bot.add_command.assert_called_once_with(core)


@pytest.mark.asyncio
async def test_usage_text_most_and_least_used() -> None:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = AdvancedUptime(MagicMock())
    cog.bot.cog_disabled_in_guild = AsyncMock(return_value=False)
    cog.config = MagicMock(show_usage_stats=AsyncMock(return_value=True))
    for name in ("ping", "ping", "help"):
        await cog.on_command(MagicMock(command=name))
    text = cog._usage_text()
    assert "`ping`, which has been used 2 times" in text
    assert "least used command is `help`, which has been used once" in text
