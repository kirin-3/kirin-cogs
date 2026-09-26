"""Taboo access command, modal, and removal button on a real Red bot."""

from typing import cast

import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from tabooaccess.tabooaccess import TabooAccess


@pytest.fixture
def red_cogs() -> list[str]:
    return ["tabooaccess"]


@pytest.mark.asyncio
async def test_member_confirms_taboo_access_then_leaves(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("TabooAccess")
    assert isinstance(cog, TabooAccess)
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    member = guild.add_member(red_env.create_user("member"))
    role = guild.create_role("Taboo")
    channel = guild.create_text_channel("taboo")
    await red_env.settle()

    await member.send(channel, f"!settaboorole {role.id}")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    await owner.send(channel, f"!settaboorole {role.id}")
    assert await cog.config.guild_from_id(guild.id).taboo_role_id() == role.id
    await owner.send(channel, "!sendtaboo")
    panel = next(message for message in channel.history() if "Click the button below" in message.content)

    shown = await member.click(panel, label="Let me in!")
    assert shown.modal is not None
    fields = [item["custom_id"] for row in shown.modal["components"] for item in row["components"]]
    accepted = await member.submit_modal(shown, {fields[0]: "yes"})
    assert accepted.response is not None and accepted.response.ephemeral
    assert "granted taboo content access" in accepted.response.content
    assert member.member is not None and member.member.get_role(role.id) is not None

    removed = await member.click(panel, label="Let me out!")
    assert removed.response is not None and removed.response.ephemeral
    assert "removed from taboo content access" in removed.response.content
    assert member.member is not None and member.member.get_role(role.id) is None
    simcord.assert_no_errors(red_env)
