"""Custom command creation and dispatch through real Red messages."""

from typing import cast

import pytest
import simcord
from redbot.core.bot import Red

from customcommand.customcommand import CustomCommand


@pytest.fixture
def red_cogs() -> list[str]:
    return ["customcommand"]


@pytest.mark.asyncio
async def test_supporter_creates_and_triggers_command(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("CustomCommand")
    assert isinstance(cog, CustomCommand)
    guild = red_env.create_guild()
    supporter_role = guild.create_role("Supporter")
    member = guild.add_member(red_env.create_user("member"))
    supporter = guild.add_member(red_env.create_user("supporter"), roles=[supporter_role])
    channel = guild.create_text_channel("general")
    await red_env.settle()
    cog.role_id = supporter_role.id

    await member.send(channel, '!cc create greeting "Hello there"')
    simcord.assert_sent(channel, contains="required role")
    await supporter.send(channel, '!cc create greeting "Hello there"')
    assert (await cog.config.guild_from_id(guild.id).commands())["greeting"] == "Hello there"
    await member.send(channel, "greeting")
    simcord.assert_sent(channel, contains="Hello there")
    simcord.assert_no_errors(red_env)
