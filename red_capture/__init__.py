"""Red cog that records exactly what the bot sends to Discord, for the Rust port's reference files.

Task 1.6 of the rust-bot-foundation change needs the real payloads Red produces for `[p]help`,
`[p]info`, `[p]set showsettings` and so on. This cog writes them to a JSON Lines file while you run
those commands, so nothing has to be copied from screenshots.

What it records, only between `[p]capture start` and `[p]capture stop`, and only for the person who
started the session:
  - the commands they run (message text and channel),
  - their button / select / modal interactions,
  - every message the bot sends, edits or deletes while running one of their commands (and in their
    DMs with the bot): the JSON body sent to Discord, so embeds, components and flags are exact,
  - the replies to their interactions (callbacks and follow-ups).

It records no tokens or headers. The file does contain the names, IDs and text of whatever the bot
posted, so use a test server and don't run commands that show secrets (`[p]set api`).

Commands (bot owner only, hidden): `[p]capture start`, `stop`, `status`, `file`.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from pathlib import Path
from typing import Any

import discord
from discord.http import HTTPClient
from discord.webhook.async_ import AsyncWebhookAdapter
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path

log = logging.getLogger("red.capture")

# Set inside this cog's own commands, so the cog's replies never end up in the capture.
_own_command: contextvars.ContextVar[bool] = contextvars.ContextVar("red_capture_own", default=False)
# Who is running the command this task belongs to. Everything the command sends from this task (or
# tasks it starts) is attributed to them; replies to other people's commands are not.
_invoker: contextvars.ContextVar[int | None] = contextvars.ContextVar("red_capture_invoker", default=None)


def _payload(kwargs: dict[str, Any]) -> Any:
    """The JSON body of a request, whether it was sent as JSON or as multipart `payload_json`."""
    if kwargs.get("json") is not None:
        return kwargs["json"]
    if kwargs.get("payload") is not None:
        return kwargs["payload"]
    for part in kwargs.get("form") or kwargs.get("multipart") or []:
        if part.get("name") == "payload_json":
            try:
                return json.loads(part["value"])
            except (TypeError, ValueError):
                return part["value"]
    return None


class RedCapture(commands.Cog):
    """Records what the bot sends while a capture session is on."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.path: Path = cog_data_path(self) / "capture.jsonl"
        self._author_id: int | None = None
        self._tokens: set[str] = set()
        self._logged: set[int] = set()
        self._count = 0
        self._patched: list[tuple[type, Any]] = []
        self.patch_http(HTTPClient)
        self.patch_adapter(AsyncWebhookAdapter)
        # Global checks run in the command's own task, which is where the invoker gets marked.
        bot.add_check(self._mark_invoker)

    # -- hooks into discord.py ------------------------------------------------------------------

    def patch_http(self, cls: type) -> None:
        """Wrap `cls.request` (discord.py's HTTPClient, or a subclass that replaces it)."""
        cog, orig = self, cls.request  # type: ignore[attr-defined]

        async def request(client: Any, route: Any, **kwargs: Any) -> Any:
            try:
                result = await orig(client, route, **kwargs)
            except BaseException as error:
                cog._record_request(route, kwargs, None, error)
                raise
            cog._record_request(route, kwargs, result, None)
            return result

        cls.request = request  # type: ignore[attr-defined]
        self._patched.append((cls, orig))

    def patch_adapter(self, cls: type) -> None:
        """Wrap the adapter that sends interaction callbacks and follow-ups."""
        cog, orig = self, cls.request  # type: ignore[attr-defined]

        async def request(adapter: Any, route: Any, session: Any, **kwargs: Any) -> Any:
            try:
                result = await orig(adapter, route, session, **kwargs)
            except BaseException as error:
                cog._record_request(route, kwargs, None, error)
                raise
            cog._record_request(route, kwargs, result, None)
            return result

        cls.request = request  # type: ignore[attr-defined]
        self._patched.append((cls, orig))

    async def _mark_invoker(self, ctx: commands.Context) -> bool:
        _invoker.set(ctx.author.id)
        # Logged here rather than from on_command: a check runs before the command does, so the
        # command is always written before the replies it causes.
        if (
            self.active
            and ctx.author.id == self._author_id
            and ctx.cog is not self
            and ctx.message.id not in self._logged
        ):
            self._logged.add(ctx.message.id)
            self._write(
                {
                    "kind": "command",
                    "content": ctx.message.content,
                    "channel_id": ctx.channel.id,
                    "guild_id": ctx.guild.id if ctx.guild else None,
                    "author_id": ctx.author.id,
                    "message_id": ctx.message.id,
                }
            )
        return True

    async def cog_unload(self) -> None:
        self.bot.remove_check(self._mark_invoker)
        for cls, orig in reversed(self._patched):
            cls.request = orig  # type: ignore[attr-defined]
        self._patched.clear()

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        _own_command.set(True)

    # -- recording -----------------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._author_id is not None

    def _write(self, entry: dict[str, Any]) -> None:
        entry["t"] = time.time()
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        self._count += 1

    def _wanted(self, route: Any) -> bool:
        token = getattr(route, "webhook_token", None)
        if token is not None:
            return token in self._tokens
        if _invoker.get() == self._author_id:
            return True
        channel_id = getattr(route, "channel_id", None)
        if channel_id is None:
            return False
        channel = self.bot.get_channel(channel_id)
        return isinstance(channel, discord.DMChannel) and getattr(channel.recipient, "id", None) == self._author_id

    def _record_request(self, route: Any, kwargs: dict[str, Any], result: Any, error: BaseException | None) -> None:
        try:
            if not self.active or _own_command.get() or route.method == "GET":
                return
            if not self._wanted(route):
                return
            entry: dict[str, Any] = {
                "kind": "request",
                "method": route.method,
                "path": route.url.split("/api/", 1)[-1],
                "payload": _payload(kwargs),
            }
            files = kwargs.get("files")
            if files:
                entry["files"] = [getattr(f, "filename", None) for f in files]
            if isinstance(result, dict):
                entry["response"] = {key: result.get(key) for key in ("id", "channel_id") if key in result}
            if error is not None:
                entry["error"] = f"{type(error).__name__}: {error}"
            self._write(entry)
        except Exception:
            log.exception("couldn't record a request")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if not self.active or interaction.user.id != self._author_id:
            return
        self._tokens.add(interaction.token)
        self._write(
            {
                "kind": "interaction",
                "type": interaction.type.name,
                "data": interaction.data,
                "channel_id": interaction.channel_id,
                "message_id": interaction.message.id if interaction.message else None,
            }
        )

    # -- commands ----------------------------------------------------------------------------

    @commands.is_owner()
    @commands.group(name="capture", hidden=True)
    async def capture(self, ctx: commands.Context) -> None:
        """Record what the bot sends, for the Rust port's reference files."""

    @capture.command(name="start")
    async def capture_start(self, ctx: commands.Context) -> None:
        """Start recording what the bot sends to you. Clears the previous capture."""
        self.path.write_text("", encoding="utf-8")
        self._count = 0
        self._tokens.clear()
        self._logged.clear()
        self._author_id = ctx.author.id
        await ctx.send(
            "Recording. Run the commands now; only your commands, your interactions and the bot's "
            "replies to them are kept. `capture stop` ends it, `capture file` sends the result."
        )

    @capture.command(name="stop")
    async def capture_stop(self, ctx: commands.Context) -> None:
        """Stop recording."""
        self._author_id = None
        await ctx.send(f"Stopped. {self._count} entries in `{self.path}`.")

    @capture.command(name="status")
    async def capture_status(self, ctx: commands.Context) -> None:
        """Say whether a capture is running and how much it holds."""
        state = "recording" if self.active else "stopped"
        await ctx.send(f"Capture is {state}; {self._count} entries in `{self.path}`.")

    @capture.command(name="file")
    async def capture_file(self, ctx: commands.Context) -> None:
        """DM you the capture file."""
        if not self.path.exists() or not self.path.stat().st_size:
            await ctx.send("Nothing captured yet.")
            return
        try:
            await ctx.author.send(file=discord.File(str(self.path), filename="capture.jsonl"))
        except discord.Forbidden:
            await ctx.send(f"I can't DM you. The file is at `{self.path}`.")
        except discord.HTTPException as error:
            await ctx.send(f"Couldn't upload it ({error}). The file is at `{self.path}`.")
        else:
            await ctx.tick()


async def setup(bot: Red) -> None:
    await bot.add_cog(RedCapture(bot))
