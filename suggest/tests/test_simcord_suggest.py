"""Suggestion submission and owner approval through Red and SimCord."""

from typing import cast
from unittest.mock import patch

import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from suggest.suggest import Suggest


@pytest.fixture
def red_cogs() -> list[str]:
    return ["suggest"]


@pytest.mark.asyncio
async def test_member_suggests_and_owner_approves(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Suggest")
    assert isinstance(cog, Suggest)
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("suggestions")
    await red_env.settle()
    cast(set[int], bot.owner_ids).add(owner.id)

    with patch("suggest.suggest.SUGGEST_CHANNEL_ID", channel.id):
        await member.send(channel, "Open suggestions")
        sticky_id = await cog.config.sticky_message_id()
        sticky = next(message for message in channel.history() if message.id == sticky_id)
        shown = await member.click(sticky, label="Make a Suggestion")
        assert shown.modal is not None
        fields = [item["custom_id"] for row in shown.modal["components"] for item in row["components"]]
        submitted = await member.submit_modal(shown, {fields[0]: "Add a games night"})
        assert submitted.followups[-1].ephemeral
        assert submitted.followups[-1].content == "Suggestion submitted!"

        suggestion = await cog.config.custom("SUGGESTION", "132").all()
        assert suggestion["author_id"] == member.id
        assert suggestion["status"] == "pending"
        await member.send(channel, "!approve 132")
        assert isinstance(red_env.errors.pop(), commands.CheckFailure)
        await owner.send(channel, "!approve 132 Games night sounds good")
        assert (await cog.config.custom("SUGGESTION", "132").status()) == "approved"
        post = next(message for message in channel.history() if message.id == suggestion["msg_id"])
        assert post.embeds[0].title == "Approved Suggestion #132"
    simcord.assert_no_errors(red_env)
