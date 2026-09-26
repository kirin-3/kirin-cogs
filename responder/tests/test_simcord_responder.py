import importlib
from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock, patch

import discord
import pytest
import simcord
from redbot.core.bot import Red

from responder.main import ResponderCog

GIF = "https://media.tenor.com/abc/potato.gif"


@pytest.fixture
def red_cogs() -> list[str]:
    return ["responder"]


@pytest.fixture
def tenor() -> Iterator[AsyncMock]:
    with patch("responder.unicornia.web.get_tenor_gifs", new=AsyncMock(return_value=[GIF])) as mock:
        yield mock


def _world(red_env: simcord.Env) -> tuple[simcord.GuildHandle, simcord.ChannelHandle, simcord.ChannelHandle]:
    """A guild with one channel the cog answers in and one it ignores."""
    guild = red_env.create_guild()
    allowed = guild.create_text_channel("bot-commands")
    other = guild.create_text_channel("general")
    const = importlib.import_module("responder.const")
    const.SERVER_PERMISSIONS[guild.id] = {"name": "Test", "allowed_channels": {allowed.id: "bot-commands"}}
    return guild, allowed, other


def _bot_messages(red_env: simcord.Env, channel: simcord.ChannelHandle) -> list[discord.Message]:
    bot_id = cast(Red, red_env.bot).user.id  # pyright: ignore[reportOptionalMemberAccess]
    return [m for m in channel.history() if m.author.id == bot_id]


@pytest.mark.asyncio
async def test_rate_only_answers_in_allowed_channels(red_env: simcord.Env) -> None:
    guild, allowed, other = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(other, "cute rate")
    assert _bot_messages(red_env, other) == []

    await member.send(allowed, "cute rate")
    [reply] = _bot_messages(red_env, allowed)
    embed = reply.embeds[0]
    assert embed.title == "❯ Cute Rate"
    assert embed.description is not None and "member" in embed.description
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_rate_anything_is_for_supporters_and_uses_tenor(red_env: simcord.Env, tenor: AsyncMock) -> None:
    guild, allowed, _ = _world(red_env)
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(allowed, "potato rate")
    assert _bot_messages(red_env, allowed) == []
    tenor.assert_not_awaited()

    await admin.send(allowed, f"potato rate <@{member.id}>")
    [reply] = _bot_messages(red_env, allowed)
    embed = reply.embeds[0]
    assert embed.title == "❯ Potato Rate"
    assert embed.description is not None and embed.description.startswith("member is ")
    assert embed.thumbnail.url == GIF
    tenor.assert_awaited_once_with("potato")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_rate_anything_falls_back_to_avatar_when_tenor_fails(red_env: simcord.Env, tenor: AsyncMock) -> None:
    tenor.side_effect = TimeoutError
    guild, allowed, _ = _world(red_env)
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    await red_env.settle()

    await admin.send(allowed, "potato rate")
    [reply] = _bot_messages(red_env, allowed)
    assert reply.embeds[0].thumbnail.url not in (None, GIF)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_the_game_has_a_silent_cooldown(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(allowed, "I lost The Game")
    await member.send(allowed, "The Game again")
    assert [m.content for m in _bot_messages(red_env, allowed)] == ["I just lost The Game."]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_unknown_target_gets_a_reply(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(allowed, "cute rate 123456789012345678")
    [reply] = _bot_messages(red_env, allowed)
    assert reply.content == 'Unable to find a member using "123456789012345678".'
    simcord.assert_no_errors(red_env)


def _responder(red_env: simcord.Env) -> ResponderCog:
    cog = cast(Red, red_env.bot).get_cog("ResponderCog")
    assert isinstance(cog, ResponderCog)
    return cog


@pytest.mark.asyncio
async def test_daddy_opt_out_command_stops_and_restores_replies(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()
    cog = _responder(red_env)

    with patch("responder.responders.daddy.random.randint", return_value=0):
        await member.send(allowed, "I'm tired")
        await member.send(allowed, "!daddyoptout")
        await member.send(allowed, "I'm still tired")

    replies = [m.content for m in _bot_messages(red_env, allowed)]
    assert replies[0] == "Hi, tired! I'm your daddy..."
    assert replies[1].startswith("You won't get daddy replies anymore.")
    assert len(replies) == 2
    assert await cog.config.user_from_id(member.id).daddy() is False

    await member.send(allowed, "!daddyoptout")
    assert _bot_messages(red_env, allowed)[-1].content.startswith("Daddy replies are back on for you.")
    assert await cog.config.all_users() == {}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_daddy_opt_out_slash_command_is_ephemeral(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, allowed, _ = _world(red_env)
    owner = guild.add_member(red_env.create_user("owner"))
    await red_env.settle()
    cast(set[int], bot.owner_ids).add(owner.id)  # what Red's --owner flag does
    await owner.send(allowed, "!slash enable daddyoptout")
    await owner.send(allowed, "!slash sync")

    result = await owner.slash(allowed, "daddyoptout")

    simcord.assert_responded(result, ephemeral=True)
    assert await _responder(red_env).config.user_from_id(owner.id).daddy() is False
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_settings_api_and_data_deletion(red_env: simcord.Env) -> None:
    cog = _responder(red_env)

    assert (await cog.settings_for(1))["daddy"]["value"] is True
    await cog.set_toggle(1, "daddy", False)
    assert (await cog.settings_for(1))["daddy"]["value"] is False
    with pytest.raises(ValueError):
        await cog.set_toggle(1, "nope", False)

    await cog.red_delete_data_for_user(requester="user", user_id=1)
    assert await cog.config.all_users() == {}
