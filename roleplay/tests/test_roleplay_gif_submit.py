"""Sending in a gif from the member site: who may, what is accepted, and the post in the review channel."""

import io
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import pytest_asyncio
import simcord
from redbot.core.bot import Red

from roleplay import const
from roleplay.main import Roleplay

GIF = b"GIF89a" + b"\0" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 100


@pytest.fixture
def red_cogs() -> list[str]:
    return ["roleplay"]


def _cog(env: simcord.Env) -> Roleplay:
    cog = cast(Red, env.bot).get_cog("Roleplay")
    assert isinstance(cog, Roleplay)
    return cog


def _member(actor: simcord.MemberActor) -> discord.Member:
    member = actor.member
    assert member is not None
    return member


@dataclass
class World:
    cog: Roleplay
    guild: simcord.GuildHandle
    uploader: discord.Member
    plain: discord.Member
    review: simcord.ChannelHandle
    clock: list[float]


@pytest_asyncio.fixture
async def world(red_env: simcord.Env, monkeypatch: pytest.MonkeyPatch) -> World:
    guild = red_env.create_guild()
    role = guild.create_role("Level 90+")
    uploader = guild.add_member(red_env.create_user("uploader"), roles=[role])
    plain = guild.add_member(red_env.create_user("plain"))
    review = guild.create_text_channel("review")
    await red_env.settle()
    monkeypatch.setattr(const, "GIF_UPLOAD_ROLES", frozenset({role.id}))
    monkeypatch.setattr(const, "GIF_REVIEW_CHANNEL", review.id)
    clock = [1000.0]
    monkeypatch.setattr("roleplay.main.monotonic", lambda: clock[0])
    return World(_cog(red_env), guild, _member(uploader), _member(plain), review, clock)


@pytest.mark.asyncio
async def test_each_upload_role_may_send_a_gif_and_others_may_not(red_env: simcord.Env) -> None:
    cog = _cog(red_env)

    def member(*role_ids: int) -> discord.Member:
        return cast(discord.Member, SimpleNamespace(roles=[SimpleNamespace(id=role_id) for role_id in role_ids]))

    assert {700121551483437128, 1458440559713718466, 721360680770469958} == const.GIF_UPLOAD_ROLES
    for role_id in (700121551483437128, 1458440559713718466, 721360680770469958):
        assert cog.can_submit_gif(member(1, role_id))
    assert not cog.can_submit_gif(member(1, 2))
    assert not cog.can_submit_gif(member())


@pytest.mark.asyncio
async def test_a_gif_is_posted_for_review_without_pinging(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, object] = {}
    send = discord.TextChannel.send

    async def spy(self: discord.TextChannel, *args: Any, **kwargs: Any) -> discord.Message:
        sent.update(kwargs)
        return await send(self, *args, **kwargs)

    monkeypatch.setattr(discord.TextChannel, "send", spy)

    await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF))

    [message] = world.review.history()
    assert [a.filename for a in message.attachments] == ["bite.gif"]
    assert "bite" in message.content and world.uploader.mention in message.content
    assert str(world.uploader.id) in message.content
    # SimCord resolves mentions itself, so check what the bot asked Discord for: nobody is pinged
    allowed = sent["allowed_mentions"]
    assert isinstance(allowed, discord.AllowedMentions) and allowed.to_dict() == {"parse": []}


@pytest.mark.asyncio
async def test_an_alias_or_capitals_name_the_same_action(world: World) -> None:
    await world.cog.submit_gif(world.uploader, "BITE", io.BytesIO(GIF))

    [message] = world.review.history()
    assert [a.filename for a in message.attachments] == ["bite.gif"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "kind", "message"),
    [
        ("bite", "png", "Only GIF files"),
        ("bite", "empty", "Only GIF files"),
        ("notanaction", "gif", "one of the roleplay actions"),
        ("../bite", "gif", "one of the roleplay actions"),
        ("bite", "big", "too big"),
    ],
)
async def test_refused_uploads_post_nothing(world: World, action: str, kind: str, message: str) -> None:
    data = {"png": PNG, "empty": b"", "gif": GIF, "big": GIF + b"\x00" * (10 * 1024 * 1024)}[kind]

    with pytest.raises(ValueError, match=message):
        await world.cog.submit_gif(world.uploader, action, io.BytesIO(data))

    assert world.review.history() == []


@pytest.mark.asyncio
async def test_the_size_limit_is_the_servers_and_is_named(world: World) -> None:
    limit = world.uploader.guild.filesize_limit

    with pytest.raises(ValueError, match=f"{limit // 1024 // 1024} MB"):
        await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF + b"\0" * limit))
    await world.cog.submit_gif(
        world.uploader, "bite", io.BytesIO(GIF + b"\0" * (limit - len(GIF)))
    )  # exactly the limit

    assert len(world.review.history()) == 1


@pytest.mark.asyncio
async def test_a_member_without_an_upload_role_is_refused(world: World) -> None:
    with pytest.raises(ValueError, match="Only supporters"):
        await world.cog.submit_gif(world.plain, "bite", io.BytesIO(GIF))

    assert world.review.history() == []


@pytest.mark.asyncio
async def test_a_second_gif_within_a_minute_is_refused_and_one_after_it_is_not(world: World) -> None:
    await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF))
    world.clock[0] += 10

    with pytest.raises(ValueError, match="Wait 50 more seconds"):
        await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF))
    assert len(world.review.history()) == 1

    world.clock[0] += 50.5  # 60.5 seconds after the first one; the refusal above didn't extend the wait
    await world.cog.submit_gif(world.uploader, "bow", io.BytesIO(GIF))
    assert len(world.review.history()) == 2


@pytest.mark.asyncio
async def test_a_refused_upload_does_not_start_the_wait(world: World) -> None:
    with pytest.raises(ValueError, match="Only GIF files"):
        await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(PNG))

    await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF))

    assert len(world.review.history()) == 1


@pytest.mark.asyncio
async def test_missing_review_channel_means_uploads_are_unavailable(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(const, "GIF_REVIEW_CHANNEL", 1)

    with pytest.raises(ValueError, match="unavailable"):
        await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF))

    assert "review channel 1 can't be found" in caplog.text
    monkeypatch.setattr(const, "GIF_REVIEW_CHANNEL", world.review.id)
    await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF))  # the failure didn't start the wait
    assert len(world.review.history()) == 1


@pytest.mark.asyncio
async def test_missing_attach_files_means_uploads_are_unavailable(
    world: World, red_env: simcord.Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked = world.guild.create_text_channel(
        "locked", overwrites={world.guild.default_role: discord.PermissionOverwrite(attach_files=False)}
    )
    await red_env.settle()
    monkeypatch.setattr(const, "GIF_REVIEW_CHANNEL", locked.id)

    with pytest.raises(ValueError, match="unavailable"):
        await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF))

    assert locked.history() == []


@pytest.mark.asyncio
async def test_a_discord_error_on_send_is_logged_and_unavailable(
    world: World, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    failing = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500, reason="x"), "boom"))
    monkeypatch.setattr(discord.TextChannel, "send", failing)

    with pytest.raises(ValueError, match="unavailable"):
        await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF))

    assert "review channel failed" in caplog.text


@pytest.mark.asyncio
async def test_nothing_is_written_to_the_images_folder(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    images = tmp_path / "images"
    (images / "bite").mkdir(parents=True)
    monkeypatch.setattr(Roleplay, "images_path", property(lambda _self: images))

    await world.cog.submit_gif(world.uploader, "bite", io.BytesIO(GIF))

    assert list(images.rglob("*")) == [images / "bite"]
    assert await world.cog.gif_actions() is not None
    assert (await world.cog.gif_page("bite", "default", 1, 1))["gifs"] == []
