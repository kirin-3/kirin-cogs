"""Owner configuration and member role checks through Red commands."""

from base64 import b64decode
from typing import cast

import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from customemoji.customemoji import CustomEmoji


@pytest.fixture
def red_cogs() -> list[str]:
    return ["customemoji"]


@pytest.mark.asyncio
async def test_owner_sets_role_and_member_needs_it_to_create(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("CustomEmoji")
    assert isinstance(cog, CustomEmoji)
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    role = guild.create_role("Emoji Maker")
    member = guild.add_member(red_env.create_user("member"))
    maker = guild.add_member(red_env.create_user("maker"), roles=[role])
    channel = guild.create_text_channel("general")
    await red_env.settle()

    cast(set[int], bot.owner_ids).add(owner.id)
    await member.send(channel, f"!ce setrole {role.id}")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    await owner.send(channel, f"!ce setrole {role.id}")
    assert await cog.config.guild_from_id(guild.id).required_role_id() == role.id

    await member.send(channel, "!ce create cookie")
    simcord.assert_sent(channel, contains="required role")
    assert await cog.config.guild_from_id(guild.id).emoji_ownership() == {}

    png = b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
    await maker.send(channel, "!ce create cookie", attachments=[("cookie.png", png)])
    simcord.assert_sent(channel, contains="created successfully")
    ownership = await cog.config.guild_from_id(guild.id).emoji_ownership()
    assert list(ownership.values()) == [maker.id]
    simcord.assert_no_errors(red_env)
