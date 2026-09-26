"""Confession button and modal on a real Red bot."""

from typing import cast
from unittest.mock import patch

import pytest
import simcord
from redbot.core.bot import Red

from confess.confess import Confess
from confess.views import CONFESSION_HEADER


@pytest.fixture
def red_cogs() -> list[str]:
    return ["confess"]


@pytest.mark.asyncio
async def test_member_submits_anonymous_confession(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Confess")
    assert isinstance(cog, Confess)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("confessions")
    await red_env.settle()

    with patch("confess.confess.CONFESSION_CHANNEL_ID", channel.id):
        await member.send(channel, "A message to start the sticky")
        sticky_id = await cog.config.sticky_message_id()
        sticky = next(message for message in channel.history() if message.id == sticky_id)
        shown = await member.click(sticky, label="Confess")
        assert shown.modal is not None
        fields = [item["custom_id"] for row in shown.modal["components"] for item in row["components"]]
        result = await member.submit_modal(shown, {fields[0]: "I ate the last cookie"})

    assert result.followups[-1].ephemeral
    assert "has been sent" in result.followups[-1].content
    confessions = [message for message in channel.history() if message.content.startswith(CONFESSION_HEADER)]
    assert len(confessions) == 1
    assert "I ate the last cookie" in confessions[0].content
    assert bot.user is not None
    assert confessions[0].author.id == bot.user.id
    simcord.assert_no_errors(red_env)
