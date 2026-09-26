"""Profile setup and sticky interactions on a real Red bot."""

from profile.profile import Profile
from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red


@pytest.fixture
def red_cogs() -> list[str]:
    return ["profile"]


@pytest.mark.asyncio
async def test_admin_sets_channel_and_member_without_profile_cannot_delete(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Profile")
    assert isinstance(cog, Profile)
    guild = red_env.create_guild()
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(manage_guild=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("profiles")
    await red_env.settle()

    await member.send(channel, f"!profileset channel {channel.id}")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)

    await admin.send(channel, f"!profileset channel {channel.id}")
    group = cog.config.guild_from_id(guild.id)
    assert await group.channel_id() == channel.id
    sticky_id = await group.sticky_message_id()
    sticky = next(message for message in channel.history() if message.id == sticky_id)
    result = await member.click(sticky, label="Delete Profile")
    assert result.response is not None
    assert result.response.ephemeral
    assert "don't have a profile" in result.response.content
    simcord.assert_no_errors(red_env)
