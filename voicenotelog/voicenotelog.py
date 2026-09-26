"""Log transcriptions of members' voice notes to a channel.

Ported from japandotorg's Seina-Cogs ``voicenotelog`` (MIT, Copyright (c) 2023-present
japandotorg). It keeps the original Config identifier and cog name, so the saved
settings carry over.

The original went through pydub and SpeechRecognition, which needs a ``flac`` binary.
SpeechRecognition only bundles one for x86, so on the aarch64 VPS every transcription
failed. This version encodes FLAC with ffmpeg and calls the same Google endpoint with
aiohttp, which also keeps the work off the event loop.
"""

import asyncio
import json
import logging
from typing import Final

import aiohttp
import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box

log = logging.getLogger("red.kirin-cogs.voicenotelog")

MIC_GIF: Final[str] = "https://cdn.discordapp.com/emojis/1164844325973270599.gif"
# The free Chromium key SpeechRecognition uses; Google may revoke it at any time.
GOOGLE_URL: Final[str] = "http://www.google.com/speech-api/v2/recognize"
GOOGLE_PARAMS: Final[dict[str, str]] = {
    "client": "chromium",
    "lang": "en-US",
    "key": "AIzaSyBOti4mM-6x9WDnZIjIeyEU21OpBXqWBgw",
    "pFilter": "0",
}
SAMPLE_RATE: Final[int] = 16_000
MAX_VOICE_NOTE_BYTES: Final[int] = 25 * 1024 * 1024
FFMPEG_TIMEOUT: Final[float] = 60.0


class TranscriptionError(Exception):
    pass


def parse_google_response(text: str) -> str | None:
    """Best transcript from the endpoint's newline-separated JSON, or None if no speech was found."""
    for line in text.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        results = data.get("result") if isinstance(data, dict) else None
        if not results or not isinstance(results, list) or not isinstance(results[0], dict):
            continue
        alternatives = [
            a for a in results[0].get("alternative", []) if isinstance(a, dict) and isinstance(a.get("transcript"), str)
        ]
        if not alternatives:
            continue
        best = max(alternatives, key=lambda a: a.get("confidence", 0))
        return best["transcript"].strip() or None
    return None


async def to_flac(audio: bytes) -> bytes:
    """Convert any audio ffmpeg understands to 16 kHz mono 16-bit FLAC."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-ac",
            "1",
            "-ar",
            str(SAMPLE_RATE),
            "-sample_fmt",
            "s16",
            "-f",
            "flac",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise TranscriptionError("ffmpeg is not installed")
    try:
        out, err = await asyncio.wait_for(proc.communicate(audio), FFMPEG_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise TranscriptionError("ffmpeg timed out")
    if proc.returncode != 0 or not out:
        raise TranscriptionError(f"ffmpeg failed: {err.decode(errors='replace').strip()[:500]}")
    return out


def find_voice_note(message: discord.Message) -> discord.Attachment | None:
    if not message.flags.voice:
        return None
    return next((a for a in message.attachments if a.is_voice_message()), None)


class VoiceNoteLog(commands.Cog):
    """Voice note logging."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=69_666_420, force_registration=True)
        self.config.register_guild(channel=None, toggle=False)
        self.config.register_global(notice=False)  # unused, kept so old data stays valid
        self.session: aiohttp.ClientSession | None = None

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))

    async def cog_unload(self) -> None:
        if self.session is not None:
            await self.session.close()

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """This cog stores no user data."""
        return

    async def transcribe(self, audio: bytes) -> str | None:
        assert self.session is not None
        flac = await to_flac(audio)
        headers = {"Content-Type": f"audio/x-flac; rate={SAMPLE_RATE}"}
        try:
            async with self.session.post(GOOGLE_URL, params=GOOGLE_PARAMS, data=flac, headers=headers) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise TranscriptionError(f"Google returned HTTP {resp.status}: {body[:200]}")
        except (aiohttp.ClientError, TimeoutError) as error:
            raise TranscriptionError(f"Request to Google failed: {error!r}")
        return parse_google_response(body)

    async def _embed(self, text: str, message: discord.Message) -> discord.Embed:
        if len(text) > 3800:  # embed descriptions cap at 4096
            text = text[:3800] + "…"
        embed = discord.Embed(
            description=(
                f"**Channel:** {message.channel.mention}\n"  # pyright: ignore[reportAttributeAccessIssue]
                f"**Transcribed Text:** {box(text)}\n"
            ),
            color=await self.bot.get_embed_color(message.channel),  # pyright: ignore[reportArgumentType]
            timestamp=message.created_at,
        )
        embed.set_thumbnail(url=MIC_GIF)
        embed.set_author(
            name=f"{message.author.display_name} ({message.author.id})",
            icon_url=message.author.display_avatar,
        )
        return embed

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        guild = message.guild
        if guild is None or message.author.bot or message.is_system():
            return
        attachment = find_voice_note(message)
        if attachment is None:
            return
        if not await self.config.guild(guild).toggle():
            return
        if await self.bot.cog_disabled_in_guild(self, guild):
            return

        channel_id = await self.config.guild(guild).channel()
        log_channel = guild.get_channel_or_thread(channel_id) if isinstance(channel_id, int) else None
        if not isinstance(log_channel, discord.TextChannel | discord.Thread):
            log.warning("Voice note logging is on in %s but the log channel is missing", guild.id)
            return
        perms = log_channel.permissions_for(guild.me)
        if not (perms.send_messages and perms.embed_links):
            log.warning("Missing send/embed permission in voice note log channel %s", log_channel.id)
            return
        if attachment.size > MAX_VOICE_NOTE_BYTES:
            log.info("Skipped %s: voice note is %s bytes", message.jump_url, attachment.size)
            return

        try:
            text = await self.transcribe(await attachment.read())
        except discord.HTTPException:
            log.debug("Voice note %s was deleted before it could be read", message.jump_url)
            return
        except TranscriptionError as error:
            log.warning("Could not transcribe %s: %s", message.jump_url, error)
            return
        if text is None:
            log.debug("No speech recognised in %s", message.jump_url)
            return

        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Jump To Message", style=discord.ButtonStyle.url, url=message.jump_url))
        try:
            await log_channel.send(embed=await self._embed(text, message), view=view)
        except discord.HTTPException:
            log.warning("Could not send voice note log to %s", log_channel.id, exc_info=True)

    @commands.group(name="voicenotelog", aliases=["vnl"])  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.mod_or_permissions(manage_guild=True)
    async def _voice_note_log(self, ctx: commands.Context) -> None:
        """Voice note logging settings."""

    @_voice_note_log.command(name="channel")
    async def _voice_note_log_channel(
        self, ctx: commands.Context, channel: discord.TextChannel | discord.Thread | None = None
    ) -> None:
        """Set the logging channel, or clear it by leaving it out."""
        assert ctx.guild is not None
        if channel is None:
            await self.config.guild(ctx.guild).channel.clear()
            await ctx.reply("Cleared the voice note logging channel.", mention_author=False)
            return
        await self.config.guild(ctx.guild).channel.set(channel.id)
        await ctx.reply(f"Configured the voice note logging channel to {channel.mention}!", mention_author=False)

    @_voice_note_log.command(name="toggle")
    async def _voice_note_log_toggle(self, ctx: commands.Context, toggle: bool) -> None:
        """Turn voice note logging on or off."""
        assert ctx.guild is not None
        await self.config.guild(ctx.guild).toggle.set(toggle)
        await ctx.reply(f"Voice note logging is now {'enabled' if toggle else 'disabled'}.", mention_author=False)

    @_voice_note_log.command(name="settings", aliases=["showsettings", "show"])
    async def _voice_note_log_settings(self, ctx: commands.Context) -> None:
        """Show the voice note logging settings."""
        assert ctx.guild is not None
        data = await self.config.guild(ctx.guild).all()
        channel_id = data.get("channel")
        channel = ctx.guild.get_channel_or_thread(channel_id) if isinstance(channel_id, int) else None
        await ctx.reply(
            f"Channel: **{channel.mention if channel else 'not set'}**\nEnabled: **{bool(data.get('toggle'))}**",
            mention_author=False,
        )
