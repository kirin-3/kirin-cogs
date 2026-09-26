"""Image filter settings and deletion via real Discord messages."""

from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from unicornsecurity.imagefilter import ImageFilter


@pytest.fixture
def red_cogs() -> list[str]:
    return ["unicornsecurity"]


@pytest.mark.asyncio
async def test_admin_sets_channel_and_only_non_tenor_images_are_removed(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("ImageFilter")
    assert isinstance(cog, ImageFilter)
    guild = red_env.create_guild()
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("gifs")
    other = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!imagefilter setchannel")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    await admin.send(channel, "!imagefilter setchannel")
    assert await cog.config.guild_from_id(guild.id).target_channel_id() == channel.id

    await member.send(channel, "https://example.com/cat.png")
    assert not any(message.content == "https://example.com/cat.png" for message in channel.history())
    simcord.assert_sent(channel, contains="only Tenor GIFs are allowed")

    await member.send(channel, "https://tenor.com/view/cat")
    assert any(message.content == "https://tenor.com/view/cat" for message in channel.history())
    await member.send(other, "https://example.com/cat.png")
    assert any(message.content == "https://example.com/cat.png" for message in other.history())
    simcord.assert_no_errors(red_env)
