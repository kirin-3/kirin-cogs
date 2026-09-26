"""Tests for the DisboardReminder cog."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from disboardreminder.disboardreminder import (
    BUMP_COOLDOWN,
    DISBOARD_BOT_ID,
    DisboardReminder,
    is_bump_success,
    render,
)

SUCCESS_IMAGE = "https://disboard.org/images/bot-command-image-bump.png"


def _message(author_id: int = DISBOARD_BOT_ID, image: str | None = SUCCESS_IMAGE) -> MagicMock:
    message = MagicMock()
    message.author.id = author_id
    message.embeds = [SimpleNamespace(image=SimpleNamespace(url=image))]
    message.created_at = discord.utils.utcnow()
    message.interaction_metadata.user = SimpleNamespace(mention="<@7>", id=7, display_name="Bumper")
    return message


def test_bump_success_needs_disboard_and_bump_image() -> None:
    assert is_bump_success(_message())
    assert not is_bump_success(_message(image=None))
    assert not is_bump_success(_message(image="https://disboard.org/images/other.png"))
    assert not is_bump_success(_message(author_id=1))


def test_render_placeholders() -> None:
    guild = SimpleNamespace(name="Unicornia", id=42)
    member = SimpleNamespace(mention="<@7>", id=7, display_name="Bumper")
    text = "{member(mention)} bumped {server}! <https://disboard.org/server/{guild(id)}> {member(nope)}"
    assert render(text, guild, member) == "<@7> bumped Unicornia! <https://disboard.org/server/42> {member(nope)}"  # pyright: ignore[reportArgumentType]
    assert render("Hi {member}, bump {server}", guild) == "Hi , bump Unicornia"  # pyright: ignore[reportArgumentType]
    assert render("Thank you! <:thx2:756477475843997770>", guild) == "Thank you! <:thx2:756477475843997770>"  # pyright: ignore[reportArgumentType]


def test_config_matches_original_cog() -> None:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = DisboardReminder(MagicMock())
    assert (cog.config.cog_name, cog.config.unique_identifier) == ("DisboardReminder", "9765573181940385953309")


def _setup(data: dict) -> tuple[DisboardReminder, MagicMock, MagicMock]:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = DisboardReminder(MagicMock())
    cog.bot.cog_disabled_in_guild = AsyncMock(return_value=False)
    group = cog.config.guild = MagicMock()
    group.return_value.all = AsyncMock(return_value=data)
    group.return_value.nextBump.set = AsyncMock()
    group.return_value.nextBump.clear = AsyncMock()

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 555
    channel.send = AsyncMock()
    guild = MagicMock()
    guild.id = 42
    guild.name = "Unicornia"
    guild.get_channel.return_value = channel
    guild.get_role.return_value = None
    return cog, guild, channel


def _data(**overrides) -> dict:
    data = {
        "channel": 555,
        "role": None,
        "message": "Bump please",
        "tyMessage": "Thanks {member(mention)}!",
        "nextBump": None,
        "lock": False,
        "clean": False,
    }
    data.update(overrides)
    return data


@pytest.mark.asyncio
async def test_bump_registers_next_bump_and_thanks() -> None:
    cog, guild, channel = _setup(_data())
    message = _message()
    message.guild = guild
    await cog.on_message_without_command(message)
    cast(MagicMock, cog.config.guild).return_value.nextBump.set.assert_awaited_once_with(
        message.created_at.timestamp() + BUMP_COOLDOWN
    )
    channel.send.assert_awaited_once_with("Thanks <@7>!")


@pytest.mark.asyncio
async def test_bump_ignored_while_one_is_registered() -> None:
    future = discord.utils.utcnow().timestamp() + 600
    cog, guild, channel = _setup(_data(nextBump=future))
    message = _message()
    message.guild = guild
    await cog.on_message_without_command(message)
    cast(MagicMock, cog.config.guild).return_value.nextBump.set.assert_not_awaited()
    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_remind_clears_next_bump_and_pings_role() -> None:
    cog, guild, channel = _setup(_data(role=9))
    role = MagicMock(mention="<@&9>")
    guild.get_role.return_value = role
    await cog.remind(guild, _data(role=9))
    cast(MagicMock, cog.config.guild).return_value.nextBump.clear.assert_awaited_once()
    args, kwargs = channel.send.await_args
    assert args == ("<@&9>: Bump please",)
    assert kwargs["allowed_mentions"].roles == [role]


@pytest.mark.asyncio
async def test_loop_only_reminds_due_guilds() -> None:
    cog, guild, _ = _setup(_data())
    now = discord.utils.utcnow().timestamp()
    cog.config.all_guilds = AsyncMock(
        return_value={1: _data(nextBump=now - 5), 2: _data(nextBump=now + 600), 3: _data(nextBump=None)}
    )
    cast(MagicMock, cog.bot.get_guild).return_value = guild
    cog.remind = AsyncMock()
    await cog.reminder_loop.coro(cog)
    cog.remind.assert_awaited_once()
    cast(MagicMock, cog.bot.get_guild).assert_called_once_with(1)
