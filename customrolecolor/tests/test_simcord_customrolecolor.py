"""Role assignment and editing through real Red commands."""

from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from customrolecolor.customrolecolor import CustomRoleColor


@pytest.fixture
def red_cogs() -> list[str]:
    return ["customrolecolor"]


@pytest.mark.asyncio
async def test_assignment_permission_and_member_rename(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("CustomRoleColor")
    assert isinstance(cog, CustomRoleColor)
    guild = red_env.create_guild()
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    member = guild.add_member(red_env.create_user("member"))
    role = guild.create_role("Personal")
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, f"!assignrole {member.id} {role.id}")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    assert await cog.config.guild_from_id(guild.id).assignments() == {}

    await admin.send(channel, f"!assignrole {member.id} {role.id}")
    assert (await cog.config.guild_from_id(guild.id).assignments())[str(member.id)] == role.id
    await member.send(channel, "!myrolename My Color")
    renamed = bot.get_guild(guild.id)
    assert renamed is not None
    renamed_role = renamed.get_role(role.id)
    assert renamed_role is not None
    assert renamed_role.name == "My Color"
    simcord.assert_no_errors(red_env)
