"""Rule acceptance command, button, and modal on a real Red bot."""

from typing import cast

import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from rulesaccept import rulesaccept
from rulesaccept.rulesaccept import RulesAccept


@pytest.fixture
def red_cogs() -> list[str]:
    return ["rulesaccept"]


@pytest.mark.asyncio
async def test_member_accepts_rules_and_picks_a_primary_role(
    red_env: simcord.Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("RulesAccept")
    assert isinstance(cog, RulesAccept)
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    member = guild.add_member(red_env.create_user("member"))
    role = guild.create_role("Member")
    femboy = guild.create_role("Femboy")
    male = guild.create_role("Male")
    monkeypatch.setattr(rulesaccept, "PRIMARY_ROLE_IDS", (femboy.id, male.id, 404))  # 404: a role that is gone
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
    phrase, select = (label["component"] for label in shown.modal["components"])
    assert [option["label"] for option in select["options"]] == ["Femboy", "Male"]
    wrong = await member.submit_modal(shown, {phrase["custom_id"]: "I agree", select["custom_id"]: [str(male.id)]})
    assert wrong.response is not None and wrong.response.ephemeral
    assert "Please type" in wrong.response.content
    assert member.member is not None and len(member.member.roles) == 1  # @everyone only

    shown = await member.click(panel, label="I have read and accept the rules.")
    assert shown.modal is not None
    phrase, select = (label["component"] for label in shown.modal["components"])
    accepted = await member.submit_modal(
        shown, {phrase["custom_id"]: '"i agree to the rules"', select["custom_id"]: [str(male.id)]}
    )
    assert accepted.response is not None and accepted.response.ephemeral
    assert "now have access" in accepted.response.content
    assert not accepted.followups
    assert member.member is not None
    assert {r.id for r in member.member.roles} == {guild.id, role.id, male.id}
    simcord.assert_no_errors(red_env)
