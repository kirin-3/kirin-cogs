"""Tests for the Sticky cog."""

from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from sticky.sticky import HEADER, Sticky, build_sticky, has_sticky


def test_build_sticky_plain_and_existing() -> None:
    assert build_sticky({"stickied": "Hi", "header_enabled": False}) == ("Hi", None)
    assert build_sticky({"stickied": "Hi", "header_enabled": True}) == (f"{HEADER}\n\nHi", None)
    content, embed = build_sticky({"advstickied": {"content": None, "embed": {"title": "T"}}, "header_enabled": True})
    assert content == HEADER
    assert embed is not None and embed.title == "T"


def test_has_sticky() -> None:
    assert has_sticky({"stickied": "x"})
    assert has_sticky({"advstickied": {"content": None, "embed": {"title": "T"}}})
    assert not has_sticky({"header_enabled": False, "advstickied": {"content": None, "embed": {}}})


def test_config_matches_original_cog() -> None:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = Sticky(MagicMock())
    assert (cog.conf.cog_name, cog.conf.unique_identifier) == ("Sticky", "1795063808")


def _cog(settings: dict) -> Sticky:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = Sticky(MagicMock())
    cog.bot.cog_disabled_in_guild = AsyncMock(return_value=False)
    group = MagicMock()
    group.last = AsyncMock(return_value=settings.get("last"))
    group.all = AsyncMock(return_value=settings)
    group.last.set = AsyncMock()
    cog.conf = MagicMock(channel=MagicMock(return_value=group))
    return cog


@pytest.mark.asyncio
async def test_delete_in_dm_or_uncached_channel_is_ignored() -> None:
    # The original crashed here with AttributeError: 'NoneType' object has no attribute 'id'.
    cog = _cog({"last": 1})
    cast(MagicMock, cog.bot.get_channel).return_value = None
    await cog.on_raw_message_delete(MagicMock(guild_id=1, channel_id=2, message_id=1))
    await cog.on_raw_message_delete(MagicMock(guild_id=None, channel_id=2, message_id=1))
    cast(MagicMock, cog.conf.channel).assert_not_called()


@pytest.mark.asyncio
async def test_new_message_reposts_and_deletes_old_sticky() -> None:
    old_time = discord.utils.utcnow() - timedelta(minutes=5)
    last_id = discord.utils.time_snowflake(old_time)
    cog = _cog({"last": last_id, "stickied": "Rules", "header_enabled": False, "cooldown": 3, "advstickied": {}})

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 10
    old = MagicMock(created_at=old_time, delete=AsyncMock())
    channel.get_partial_message.return_value = old
    channel.send = AsyncMock(return_value=MagicMock(id=999))
    message = MagicMock(channel=channel, id=last_id + 1, created_at=discord.utils.utcnow())

    await cog.on_message(message)

    channel.send.assert_awaited_once_with("Rules", embed=discord.utils.MISSING)
    cast(MagicMock, cog.conf.channel).return_value.last.set.assert_awaited_once_with(999)
    old.delete.assert_awaited_once()
