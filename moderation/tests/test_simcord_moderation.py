"""Mute and unmute through Red's command and permission checks."""

from typing import cast
from unittest.mock import patch

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from moderation.moderation import Moderation


@pytest.fixture
def red_cogs() -> list[str]:
    return ["moderation"]


@pytest.mark.asyncio
async def test_staff_mutes_and_restores_member_roles(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Moderation")
    assert isinstance(cog, Moderation)
    guild = red_env.create_guild()
    staff_role = guild.create_role("Staff", permissions=discord.Permissions(manage_roles=True))
    regular_role = guild.create_role("Regular")
    muted_role = guild.create_role("Muted")
    staff = guild.add_member(red_env.create_user("staff"), roles=[staff_role])
    member = guild.add_member(red_env.create_user("member"), roles=[regular_role])
    bystander = guild.add_member(red_env.create_user("bystander"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    with patch("moderation.moderation.MUTED_ROLE_ID", muted_role.id):
        await bystander.send(channel, f"!mute {member.id}")
        assert isinstance(red_env.errors.pop(), commands.CheckFailure)
        assert await cog.config.member_from_ids(guild.id, member.id).mute() is None

        await staff.send(channel, f"!mute {member.id}")
        record = await cog.config.member_from_ids(guild.id, member.id).mute()
        assert isinstance(record, dict)
        assert regular_role.id in record["roles"]
        current = bot.get_guild(guild.id)
        assert current is not None
        muted = current.get_member(member.id)
        assert muted is not None
        assert muted.get_role(muted_role.id) is not None
        assert muted.get_role(regular_role.id) is None

        await staff.send(channel, f"!unmute {member.id}")
        restored = current.get_member(member.id)
        assert restored is not None
        assert restored.get_role(muted_role.id) is None
        assert restored.get_role(regular_role.id) is not None
        assert await cog.config.member_from_ids(guild.id, member.id).mute() is None
    simcord.assert_no_errors(red_env)
