"""Tests for the VoiceNoteLog cog."""

import shutil
import subprocess
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from voicenotelog.voicenotelog import (
    TranscriptionError,
    VoiceNoteLog,
    find_voice_note,
    parse_speech_response,
    to_flac,
)


def test_parse_joins_results_using_top_alternative() -> None:
    data = {
        "results": [
            {"alternatives": [{"transcript": "hello world", "confidence": 0.9}, {"transcript": "hello word"}]},
            {"alternatives": [{"transcript": " how are you "}]},
            {"alternatives": []},
        ]
    }
    assert parse_speech_response(data) == "hello world how are you"


@pytest.mark.parametrize(
    "data", [None, {}, {"results": []}, {"results": [{"alternatives": []}]}, [1], {"results": "x"}]
)
def test_parse_returns_none_without_speech(data: object) -> None:
    assert parse_speech_response(data) is None


def test_find_voice_note_needs_flag_and_voice_attachment() -> None:
    voice = MagicMock(is_voice_message=MagicMock(return_value=True))
    other = MagicMock(is_voice_message=MagicMock(return_value=False))
    msg = SimpleNamespace(flags=SimpleNamespace(voice=True), attachments=[other, voice])
    assert find_voice_note(msg) is voice  # pyright: ignore[reportArgumentType]
    msg.flags.voice = False
    assert find_voice_note(msg) is None  # pyright: ignore[reportArgumentType]


def test_config_matches_original_cog() -> None:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = VoiceNoteLog(MagicMock())
    assert (cog.config.cog_name, cog.config.unique_identifier) == ("VoiceNoteLog", "69666420")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.asyncio
async def test_to_flac_converts_ogg_and_rejects_garbage() -> None:
    ogg = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libopus", "-f", "ogg", "-"],
        capture_output=True,
        check=True,
    ).stdout
    assert (await to_flac(ogg))[:4] == b"fLaC"
    with pytest.raises(TranscriptionError):
        await to_flac(b"definitely not audio")


def _cog_with_key(key: str | None) -> VoiceNoteLog:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = VoiceNoteLog(MagicMock())
    cog.bot.get_shared_api_tokens = AsyncMock(return_value={"api_key": key} if key else {})
    return cog


@pytest.mark.asyncio
async def test_transcribe_polls_operation_until_done() -> None:
    cog = _cog_with_key("k")
    done = {"name": "op1", "done": True, "response": {"results": [{"alternatives": [{"transcript": "hi"}]}]}}
    request = AsyncMock(side_effect=[{"name": "op1"}, {"name": "op1", "done": False}, done])
    with (
        patch.object(cog, "_speech_request", request),
        patch("voicenotelog.voicenotelog.to_flac", AsyncMock(return_value=b"fLaC")),
        patch("voicenotelog.voicenotelog.POLL_INTERVAL", 0),
    ):
        assert await cog.transcribe(b"ogg") == "hi"
    first, *polls = request.await_args_list
    assert first.args[:3] == ("POST", "speech:longrunningrecognize", "k")
    assert first.args[3]["audio"]["content"] == "ZkxhQw=="
    assert [c.args[:3] for c in polls] == [("GET", "operations/op1", "k")] * 2


@pytest.mark.asyncio
async def test_transcribe_raises_on_missing_key_or_operation_error() -> None:
    with pytest.raises(TranscriptionError, match="no API key"):
        await _cog_with_key(None).transcribe(b"ogg")
    cog = _cog_with_key("k")
    failed = AsyncMock(return_value={"name": "op1", "done": True, "error": {"code": 3, "message": "bad audio"}})
    with (
        patch.object(cog, "_speech_request", failed),
        patch("voicenotelog.voicenotelog.to_flac", AsyncMock(return_value=b"fLaC")),
        pytest.raises(TranscriptionError, match="bad audio"),
    ):
        await cog.transcribe(b"ogg")


def _setup(transcript: str | None) -> tuple[VoiceNoteLog, MagicMock, MagicMock]:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = VoiceNoteLog(MagicMock())
    cog.bot.cog_disabled_in_guild = AsyncMock(return_value=False)
    cog.bot.get_embed_color = AsyncMock(return_value=discord.Color.blue())
    group = cog.config.guild = MagicMock()
    group.return_value.toggle = AsyncMock(return_value=True)
    group.return_value.channel = AsyncMock(return_value=555)
    cog.transcribe = AsyncMock(return_value=transcript)

    log_channel = MagicMock(spec=discord.TextChannel)
    log_channel.id = 555
    log_channel.send = AsyncMock()
    guild = MagicMock()
    guild.id = 1
    guild.get_channel_or_thread.return_value = log_channel

    attachment = MagicMock(size=1000, read=AsyncMock(return_value=b"ogg"))
    attachment.is_voice_message.return_value = True
    message = MagicMock()
    message.guild = guild
    message.author.bot = False
    message.author.display_name = "Someone"
    message.author.id = 7
    message.author.display_avatar = "https://example.invalid/a.png"
    message.is_system.return_value = False
    message.flags.voice = True
    message.attachments = [attachment]
    message.jump_url = "https://discord.com/channels/1/2/3"
    message.created_at = discord.utils.utcnow()
    return cog, message, log_channel


@pytest.mark.asyncio
async def test_listener_posts_transcript() -> None:
    cog, message, log_channel = _setup("hello world")
    await cog.on_message(message)
    log_channel.send.assert_awaited_once()
    assert "hello world" in log_channel.send.await_args.kwargs["embed"].description


@pytest.mark.asyncio
async def test_listener_stays_quiet_on_failures_and_keeps_toggle() -> None:
    cog, message, log_channel = _setup(None)
    await cog.on_message(message)
    cast(AsyncMock, cog.transcribe).side_effect = TranscriptionError("boom")
    await cog.on_message(message)
    log_channel.send.assert_not_awaited()
    cast(MagicMock, cog.config.guild).return_value.toggle.clear.assert_not_called()
