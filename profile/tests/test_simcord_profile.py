"""Profile setup and sticky interactions on a real Red bot."""

import asyncio
from profile.profile import Profile
from typing import Any, cast
from unittest.mock import patch

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


@pytest.mark.asyncio
async def test_two_builders_submitted_together_post_one_profile(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Profile")
    assert isinstance(cog, Profile)
    guild = red_env.create_guild()
    owner = simcord.MemberActor(red_env, guild, guild.owner)
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("profiles")
    await red_env.settle()
    await owner.send(channel, f"!profileset channel {channel.id}")
    sticky_id = await cog.config.guild_from_id(guild.id).sticky_message_id()
    sticky = next(message for message in channel.history() if message.id == sticky_id)

    # Two builders are open, then both are submitted at the same moment
    submitted = asyncio.Event()

    class Builder(discord.ui.View):
        def __init__(self, *_args: object) -> None:
            super().__init__()
            self.submitted = True
            self.picture = None
            self.data = {"name": "Alice", "age": 28, "location": "Here", "gender": "Woman", "sexuality": "Gay"}

        async def wait(self) -> bool:
            await red_env.external_wait(submitted.wait(), reason="the member fills in the builder")
            return False

    send = discord.TextChannel.send

    async def slow_send(self: discord.TextChannel, *args: Any, **kwargs: Any) -> discord.Message:
        await asyncio.sleep(0)  # A real request lets the other submit run meanwhile
        return await send(self, *args, **kwargs)

    with patch("profile.profile.ProfileBuilderView", Builder), patch.object(discord.TextChannel, "send", slow_send):
        await member.click(sticky, label="Create/Edit Profile")
        await member.click(sticky, label="Create/Edit Profile")
        submitted.set()
        await red_env.settle()

    posts = [message for message in channel.history() if message.embeds and message.embeds[0].title == "Alice"]
    assert len(posts) == 1
    assert await cog.config.member_from_ids(guild.id, member.id).message_id() == posts[0].id
    simcord.assert_no_errors(red_env)
