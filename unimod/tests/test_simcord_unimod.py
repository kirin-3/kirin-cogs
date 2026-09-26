"""Owner configuration and message moderation through a real Red bot."""

from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from unimod.unimod import AIAnalysisResult, UniMod


@pytest.fixture
def red_cogs() -> list[str]:
    return ["unimod"]


@pytest.fixture(autouse=True)
def no_nltk_download() -> Iterator[None]:
    with patch.object(UniMod, "_download_nltk_data"):
        yield


@pytest.mark.asyncio
async def test_owner_configures_moderation_and_message_alerts(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("UniMod")
    assert isinstance(cog, UniMod)
    guild = red_env.create_guild()
    owner = guild.add_member(red_env.create_user("owner"))
    member = guild.add_member(red_env.create_user("member"))
    general = guild.create_text_channel("general")
    alerts = guild.create_text_channel("alerts")
    elsewhere = guild.create_text_channel("elsewhere")
    await red_env.settle()
    bot.owner_ids = set(bot.owner_ids or ()) | {owner.id}

    await member.send(general, "!unimod toggle")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    assert await cog.config.guild_from_id(guild.id).enabled() is False

    await owner.send(general, f"!unimod whitelist {general.id}")
    await owner.send(general, f"!unimod channel {alerts.id}")
    await owner.send(general, "!unimod toggle")
    group = cog.config.guild_from_id(guild.id)
    assert await group.whitelisted_channels() == [general.id]
    assert await group.alert_channel_id() == alerts.id
    assert await group.enabled() is True

    await member.send(elsewhere, "I hate you, you are terrible and disgusting!")
    await owner.send(general, "!unimod stats")
    assert cog.stats["messages_processed"] == 0

    result = AIAnalysisResult(True, 0.95, ["7.1"], "medium", "Harassment", None)
    with patch.object(cog, "_analyze_with_ai", new_callable=AsyncMock, return_value=result) as analyze:
        await member.send(general, "I hate you, you are terrible and disgusting!")
        await red_env.settle()

    analyze.assert_awaited_once()
    assert analyze.await_args is not None
    assert "I hate you" in analyze.await_args.args[1]
    assert cog.stats["messages_processed"] == 1
    assert cog.stats["violations_found"] == 1
    assert not cog.channel_buffers[general.id]
    alert = alerts.last_message
    assert alert is not None
    assert alert.embeds[0].title == "⚠️ Potential Rule Violation Detected"
    assert any(field.name == "Severity" and field.value == "Medium" for field in alert.embeds[0].fields)
    simcord.assert_no_errors(red_env)
