"""A real message travels through automod's rule and action path."""

from typing import cast
from unittest.mock import patch

import pytest
import simcord
from redbot.core.bot import Red

from automod.automod import AutoMod
from automod.tests.helpers import document, rule, ruleset


@pytest.fixture
def red_cogs() -> list[str]:
    return ["automod"]


@pytest.mark.asyncio
async def test_invite_rule_dry_run_then_deletes_message(red_env: simcord.Env) -> None:
    cog = cast(Red, red_env.bot).get_cog("AutoMod")
    assert isinstance(cog, AutoMod)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await cog.save(document(ruleset("links", [rule("invite", [{"type": "invite"}], [{"type": "delete"}])])))

    with patch("automod.automod.GUILD_ID", guild.id):
        first = await member.send(channel, "discord.gg/first")
        assert any(message.id == first.id for message in channel.history())
        [dry_run] = await cog.action_log()
        assert dry_run["actions"][0]["status"] == "would"
        assert "discord.gg/first" not in str(dry_run)

        await cog.set_dry_run(False)
        second = await member.send(channel, "discord.gg/second")
        assert all(message.id != second.id for message in channel.history())
        [applied, _] = await cog.action_log()
        assert applied["actions"][0]["status"] == "done"
        assert applied["user_id"] == member.id
    simcord.assert_no_errors(red_env)
