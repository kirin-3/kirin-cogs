"""Rule acceptance command, button, and modal on a real Red bot."""

from typing import cast

import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from rulesaccept.rulesaccept import RulesAccept


@pytest.fixture
def red_cogs() -> list[str]:
    return ["rulesaccept"]


@pytest.mark.asyncio
async def test_member_accepts_rules_after_confirming_exact_text(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("RulesAccept")
    assert isinstance(cog, RulesAccept)
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    member = guild.add_member(red_env.create_user("member"))
    role = guild.create_role("Member")
    channel = guild.create_text_channel("rules")
    await red_env.settle()

    await member.send(channel, f"!setrole {role.id}")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    await owner.send(channel, f"!setrole {role.id}")
    assert await cog.config.guild_from_id(guild.id).member_role_id() == role.id
    await owner.send(channel, "!sendrules")
    panel = next(message for message in channel.history() if "Please read the rules" in message.content)

    shown = await member.click(panel, label="I have read and accept the rules.")
    assert shown.modal is not None
    fields = [item["custom_id"] for row in shown.modal["components"] for item in row["components"]]
    wrong = await member.submit_modal(shown, {fields[0]: "I agree"})
    assert wrong.response is not None and wrong.response.ephemeral
    assert "must type exactly" in wrong.response.content
    assert member.member is not None and member.member.get_role(role.id) is None

    shown = await member.click(panel, label="I have read and accept the rules.")
    accepted = await member.submit_modal(shown, {fields[0]: "I agree to the rules."})
    assert accepted.response is not None and accepted.response.ephemeral
    assert "given access" in accepted.response.content
    assert member.member is not None and member.member.get_role(role.id) is not None
    simcord.assert_no_errors(red_env)
