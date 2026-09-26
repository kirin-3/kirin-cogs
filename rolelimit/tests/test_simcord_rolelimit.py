"""Role limit settings and member updates through a real Red bot."""

from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from rolelimit.rolelimit import RoleLimit


@pytest.fixture
def red_cogs() -> list[str]:
    return ["rolelimit"]


@pytest.mark.asyncio
async def test_admin_sets_ranked_roles_and_new_role_replaces_lower_one(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("RoleLimit")
    assert isinstance(cog, RoleLimit)
    guild = red_env.create_guild()
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    lower = guild.create_role("Lower")
    higher = guild.create_role("Higher")
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    member = guild.add_member(red_env.create_user("member"), roles=[lower])
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, f"!rolelimit set {lower.id} {higher.id}")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    await admin.send(channel, f"!rolelimit set {lower.id} {higher.id}")
    assert await cog.config.guild_from_id(guild.id).roles() == [lower.id, higher.id]

    current_guild = bot.get_guild(guild.id)
    assert current_guild is not None
    current_member = current_guild.get_member(member.id)
    higher_role = current_guild.get_role(higher.id)
    assert current_member is not None and higher_role is not None
    await current_member.add_roles(higher_role)
    await red_env.settle()
    updated = current_guild.get_member(member.id)
    assert updated is not None
    assert updated.get_role(higher.id) is not None
    assert updated.get_role(lower.id) is None
    simcord.assert_no_errors(red_env)
