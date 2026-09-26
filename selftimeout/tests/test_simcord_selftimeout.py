from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red


@pytest.fixture
def red_cogs() -> list[str]:
    return ["selftimeout"]


def _world(red_env: simcord.Env) -> tuple[simcord.GuildHandle, simcord.ChannelHandle]:
    guild = red_env.create_guild()
    return guild, guild.create_text_channel("general")


def _member(red_env: simcord.Env, member_id: int) -> discord.Member:
    guild = cast(Red, red_env.bot).guilds[0]
    found = guild.get_member(member_id)
    assert found is not None
    return found


@pytest.mark.asyncio
async def test_confirming_times_out_and_cleans_up(red_env: simcord.Env) -> None:
    guild, channel = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(channel, "!break 2h")
    prompt = channel.last_message
    assert prompt is not None and "2 hours" in prompt.content
    assert _member(red_env, member.id).timed_out_until is None

    await member.click(prompt, label="Take a break")

    until = _member(red_env, member.id).timed_out_until
    assert until is not None
    assert abs((until - discord.utils.utcnow()).total_seconds() - 7200) < 60
    assert channel.history() == []
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_cancelling_leaves_member_alone(red_env: simcord.Env) -> None:
    guild, channel = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(channel, "!break 30")
    prompt = channel.last_message
    assert prompt is not None
    await member.click(prompt, label="Cancel")

    assert _member(red_env, member.id).timed_out_until is None
    assert channel.history() == []
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_rejects_over_28_days_and_administrators(red_env: simcord.Env) -> None:
    guild, channel = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    await red_env.settle()

    await member.send(channel, "!break 30d")
    assert isinstance(red_env.errors.pop(), commands.BadArgument)

    await admin.send(channel, "!break 1h")
    simcord.assert_sent(channel, contains="time out administrators")
    assert _member(red_env, admin.id).timed_out_until is None
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_slash_confirmation_is_ephemeral(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, channel = _world(red_env)
    owner = guild.add_member(red_env.create_user("owner"))
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()
    cast(set[int], bot.owner_ids).add(owner.id)  # what Red's --owner flag does
    await owner.send(channel, "!slash enable break")
    await owner.send(channel, "!slash sync")

    result = await member.slash(channel, "break", duration="1d")
    assert result.response is not None and result.response.ephemeral
    await member.click(result.response, label="Take a break")

    assert _member(red_env, member.id).timed_out_until is not None
    simcord.assert_no_errors(red_env)
