import asyncio
import contextlib
import logging
import math
import os
import time
from collections.abc import Mapping
from typing import TypedDict

import discord
from discord.ext import tasks
from redbot.core import Config, app_commands, commands

from .openai import DEFAULT_ENDPOINT, DEFAULT_MODEL, AIRequestError, OpenAIClient
from .persona import PersonaManager

log = logging.getLogger("red.unicorn_ai")

MIN_INTERVAL = 60
MAX_INTERVAL = 86400
DEFAULT_INTERVAL = 300
MIN_HISTORY = 1
MAX_HISTORY = 200
DEFAULT_HISTORY = 50
# Consecutive scheduled failures double the wait, up to this many doublings (and MAX_INTERVAL).
MAX_BACKOFF_DOUBLINGS = 8


class ChannelSettings(TypedDict):
    enabled: bool
    interval: int
    active_persona: str | None
    last_run: float


class GlobalSettings(TypedDict):
    history_limit: int
    openai_endpoint: str
    openai_model: str


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, parsed))


def normalize_channel_settings(value: object) -> ChannelSettings:
    """Return a complete scheduler-safe channel configuration."""
    raw = value if isinstance(value, Mapping) else {}
    persona = raw.get("active_persona")
    if not isinstance(persona, str) or not persona.strip():
        persona = None
    raw_last_run = raw.get("last_run", 0)
    try:
        last_run = float(raw_last_run)  # type: ignore[arg-type]
        if not math.isfinite(last_run) or last_run < 0:
            last_run = 0.0
    except (TypeError, ValueError, OverflowError):
        last_run = 0.0
    return {
        "enabled": raw.get("enabled") is True,
        "interval": _bounded_int(
            raw.get("interval"), default=DEFAULT_INTERVAL, minimum=MIN_INTERVAL, maximum=MAX_INTERVAL
        ),
        "active_persona": persona,
        "last_run": last_run,
    }


def normalize_global_settings(value: object) -> GlobalSettings:
    """Return complete global settings without trusting Config shapes."""
    raw = value if isinstance(value, Mapping) else {}
    openai_endpoint = raw.get("openai_endpoint")
    if not isinstance(openai_endpoint, str) or not openai_endpoint.strip():
        openai_endpoint = DEFAULT_ENDPOINT
    openai_model = raw.get("openai_model")
    if not isinstance(openai_model, str) or not openai_model.strip():
        openai_model = DEFAULT_MODEL
    return {
        "history_limit": _bounded_int(
            raw.get("history_limit"), default=DEFAULT_HISTORY, minimum=MIN_HISTORY, maximum=MAX_HISTORY
        ),
        "openai_endpoint": openai_endpoint,
        "openai_model": openai_model,
    }


def normalize_endpoint(url: str) -> str | None:
    """Return a chat completions URL for an OpenAI-compatible base or full URL, or None if it is not http(s)."""
    url = url.strip().strip("<>").rstrip("/")
    if not url.lower().startswith(("https://", "http://")) or len(url.split("://", 1)[1]) == 0:
        return None
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    return url


def retry_delay(interval: int, failures: int) -> int:
    """Seconds to wait before the next scheduled run after ``failures`` consecutive failed runs."""
    if failures <= 0:
        return interval
    return min(MAX_INTERVAL, interval * 2 ** min(failures - 1, MAX_BACKOFF_DOUBLINGS))


def _summon_user_cd(ctx: commands.Context) -> commands.Cooldown | None:
    if ctx.author.id in ctx.bot.owner_ids:
        return None
    return commands.Cooldown(1, 3600)


def _summon_channel_cd(ctx: commands.Context) -> commands.Cooldown | None:
    if ctx.author.id in ctx.bot.owner_ids:
        return None
    return commands.Cooldown(1, 600)


class UnicornAI(commands.Cog):
    """
    Autonomous AI persona using OpenAI-compatible endpoints (NanoGPT by default).
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9988776655, force_registration=True)

        self._channel_locks: dict[int, asyncio.Lock] = {}
        self._generation_semaphore = asyncio.Semaphore(2)
        self._active_channels: set[int] = set()
        self._background_tasks: set[asyncio.Task[None]] = set()
        # Consecutive failed scheduled runs per channel, used to back off retries
        self._failures: dict[int, int] = {}
        # Webhooks this bot owns, so persona messages are recognised as the persona's own,
        # and every webhook already looked up, so foreign webhooks do not trigger a refetch each run
        self._own_webhook_ids: set[int] = set()
        self._seen_webhook_ids: set[int] = set()

        # Channel-specific config
        default_channel = {
            "enabled": False,
            "interval": 300,  # 5 minutes default
            "active_persona": None,
            "last_run": 0,
        }
        self.config.register_channel(**default_channel)

        # Global config for API/System settings
        default_global = {
            "history_limit": 50,
            "openai_endpoint": DEFAULT_ENDPOINT,
            "openai_model": DEFAULT_MODEL,
        }
        self.config.register_global(**default_global)

        # User config for opt-out
        default_user = {"opt_out": False}
        self.config.register_user(**default_user)

        self.cog_path = os.path.dirname(__file__)
        self.data_path = os.path.join(self.cog_path, "data", "personas")

        self.openai = OpenAIClient(self.bot)
        self.personas = PersonaManager(self.data_path)

        # Start loop
        self.auto_message_loop.start()

    async def cog_unload(self) -> None:
        self.auto_message_loop.cancel()
        tasks_to_cancel = list(self._background_tasks)
        for task in tasks_to_cancel:
            task.cancel()
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Delete the user's persistent AI opt-out preference."""
        await self.config.user_from_id(user_id).clear()

    def _track_task(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_task_done)

    def _background_task_done(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            log.error("Scheduled UnicornAI task failed", exc_info=exception)

    @tasks.loop(seconds=60)
    async def auto_message_loop(self):
        """
        Background loop to trigger AI messages.
        Runs every minute and checks all channels.
        """
        await self.bot.wait_until_ready()

        all_channels = await self.config.all_channels()
        now = time.time()

        if not isinstance(all_channels, Mapping):
            log.warning("Malformed UnicornAI channel configuration root; skipping scheduler pass")
            return

        for raw_channel_id, raw_settings in all_channels.items():
            settings = normalize_channel_settings(raw_settings)
            if not settings["enabled"]:
                continue

            if isinstance(raw_channel_id, bool):
                continue
            try:
                channel_id = int(raw_channel_id)
            except (TypeError, ValueError, OverflowError):
                continue
            interval = retry_delay(int(settings["interval"]), self._failures.get(channel_id, 0))
            last_run = float(settings["last_run"])

            if (now - last_run) >= interval:
                channel = self.bot.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    if channel_id in self._active_channels:
                        continue

                    self._track_task(self._trigger_ai(channel=channel))

    @auto_message_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    def _get_channel_lock(self, channel_id: int) -> asyncio.Lock:
        if channel_id not in self._channel_locks:
            self._channel_locks[channel_id] = asyncio.Lock()
        return self._channel_locks[channel_id]

    async def _trigger_ai(
        self,
        channel: discord.TextChannel | None = None,
        ctx: commands.Context | None = None,
        persona_override: str | None = None,
    ) -> None:
        target_channel = ctx.channel if ctx else channel
        if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
            return

        channel_id = target_channel.id
        if channel_id in self._active_channels:
            if ctx:
                await ctx.send("An AI response is already being generated for this channel.", ephemeral=True)
            return

        # This claim occurs before the first await, so separately scheduled tasks cannot
        # both fetch history and generate for the same channel.
        self._active_channels.add(channel_id)
        try:
            async with self._get_channel_lock(channel_id):
                posted = await self._trigger_ai_claimed(channel, ctx, persona_override)
                if posted or not ctx:
                    await self._record_run(target_channel, posted=posted)
        finally:
            self._active_channels.discard(channel_id)

    async def _record_run(self, channel: discord.TextChannel | discord.Thread, *, posted: bool) -> None:
        """Restart the channel's timer; failed scheduled runs back off instead of retrying every minute."""
        await self.config.channel(channel).last_run.set(time.time())
        if posted:
            self._failures.pop(channel.id, None)
            return
        failures = self._failures.get(channel.id, 0) + 1
        self._failures[channel.id] = failures
        interval = normalize_channel_settings(await self.config.channel(channel).all())["interval"]
        log.warning(
            f"UnicornAI run in channel {channel.id} posted nothing ({failures} in a row); "
            f"next attempt in {retry_delay(interval, failures)}s"
        )

    async def _trigger_ai_claimed(
        self,
        channel: discord.TextChannel | None = None,
        ctx: commands.Context | None = None,
        persona_override: str | None = None,
    ) -> bool:
        """
        Core logic to fetch history and generate response.
        Can be triggered by loop (passed channel) or manual command (passed ctx).
        Returns whether a reply was posted.
        """
        # Resolve target channel
        if ctx:
            target_channel = ctx.channel
        else:
            target_channel = channel

        if not target_channel:
            return False

        # Fetch settings — only guild channels are tracked in config
        if not isinstance(target_channel, (discord.TextChannel, discord.Thread)):
            return False
        settings = normalize_channel_settings(await self.config.channel(target_channel).all())
        global_settings = normalize_global_settings(await self.config.all())

        # If manual trigger, ignore 'enabled' check
        if not ctx and settings["enabled"] is not True:
            return False

        persona_name = persona_override or settings["active_persona"]
        if not persona_name:
            if ctx:
                await ctx.send("No active persona set (and no override provided).")
            return False

        persona = await asyncio.to_thread(self.personas.load_persona, persona_name)
        if not persona:
            if ctx:
                await ctx.send(f"Failed to load persona '{persona_name}'.")
            return False

        # 2. Fetch History
        try:
            # Use persona limit if set, otherwise global
            raw_limit = persona.history_limit if persona.history_limit is not None else global_settings["history_limit"]
            try:
                limit = max(1, min(200, int(raw_limit)))
            except (ValueError, TypeError):
                limit = 50

            # Ensure we are in a text channel or thread
            if not hasattr(target_channel, "history"):
                if ctx:
                    await ctx.send("Cannot fetch history from this channel type.")
                return False

            messages = [m async for m in target_channel.history(limit=limit)]
            messages.reverse()  # Oldest first
        except Exception as e:
            log.error(f"Failed to fetch history: {e}")
            if ctx:
                await ctx.send(f"Error fetching history: {e}")
            return False

        # 3. Format History (With Opt-Out Check)
        own_webhook_ids = await self._get_own_webhook_ids(target_channel, messages)
        formatted_history = []
        for msg in messages:
            from_bot = msg.author.id == self.bot.user.id
            from_own_webhook = msg.webhook_id is not None and msg.webhook_id in own_webhook_ids
            # Check opt-out status for user messages
            if not from_bot and not from_own_webhook and await self.config.user(msg.author).opt_out():
                continue

            # Persona replies arrive through our webhook; only this persona's own lines are the model's turns.
            is_model = from_bot or (from_own_webhook and msg.author.display_name == persona.name)
            role = "model" if is_model else "user"
            content = msg.clean_content
            if not content:
                continue  # Skip empty messages

            formatted_history.append({"role": role, "parts": [{"text": f"{msg.author.display_name}: {content}"}]})

        # 4. Generate Response
        if ctx:
            await ctx.send("Generating response...")

        async with self._generation_semaphore:
            return await self._do_generate_and_send(ctx, target_channel, global_settings, formatted_history, persona)

    async def _get_own_webhook_ids(
        self, channel: discord.TextChannel | discord.Thread, messages: list[discord.Message]
    ) -> set[int]:
        """Return this bot's webhook IDs, fetching the channel's webhooks only for unrecognised webhook messages."""
        unknown = {m.webhook_id for m in messages if m.webhook_id is not None} - self._seen_webhook_ids
        if not unknown:
            return self._own_webhook_ids
        parent = channel.parent if isinstance(channel, discord.Thread) else channel
        if not isinstance(parent, discord.TextChannel) or not parent.permissions_for(parent.guild.me).manage_webhooks:
            return self._own_webhook_ids
        try:
            webhooks = await parent.webhooks()
        except discord.HTTPException as e:
            log.warning(f"Could not list webhooks in channel {parent.id}: {e}")
            return self._own_webhook_ids
        self._own_webhook_ids.update(w.id for w in webhooks if w.user and w.user.id == self.bot.user.id)
        # Unknown IDs not in the list belong to deleted or foreign webhooks; either way they are not ours.
        self._seen_webhook_ids.update(unknown, (w.id for w in webhooks))
        return self._own_webhook_ids

    async def _do_generate_and_send(self, ctx, target_channel, global_settings, formatted_history, persona) -> bool:
        """Generate a reply and post it as the persona. Returns whether a reply was posted."""
        # Get API key from Red's shared tokens
        api_key = await self.bot.get_shared_api_tokens("openai")
        if not api_key.get("api_key"):
            log.warning("UnicornAI API key is not set")
            if ctx:
                await ctx.send("API key not set. Use `[p]ai key <api_key>` to configure.")
            return False

        try:
            response = await self.openai.generate_response(
                endpoint=global_settings["openai_endpoint"],
                api_key=api_key["api_key"],
                model=global_settings["openai_model"],
                system_instruction=persona.system_prompt,
                history=formatted_history,
                after_context=persona.after_context,
            )
        except AIRequestError as e:
            # Errors are never posted as the persona; only the invoker is told.
            if ctx:
                detail = f": {e}" if await self.bot.is_owner(ctx.author) else ". Check the bot logs."
                await ctx.send(f"The AI request failed{detail}")
            return False

        if not response:
            if ctx:
                await ctx.send("The AI returned an empty response.")
            return False

        # 5. Send
        try:
            await self._send_response(target_channel, response, persona)
        except Exception as e:
            log.error(f"Failed to send UnicornAI message in channel {target_channel.id}: {e}")
            if ctx:
                await ctx.send(f"Failed to send message: {e}")
            return False
        return True

    async def _send_response(self, channel, content: str, persona):
        """
        Sends the response via Webhook if possible (for persona impersonation),
        otherwise falls back to standard message.
        """
        # Truncate content to 2000 chars to avoid Discord 400s
        if len(content) > 2000:
            content = content[:1997] + "..."

        allowed_mentions = discord.AllowedMentions.none()

        # Check if we can use webhooks (Guild channels only)
        if not hasattr(channel, "guild"):
            await channel.send(content, allowed_mentions=allowed_mentions)
            return

        perms = channel.permissions_for(channel.guild.me)
        if not perms.manage_webhooks:
            await channel.send(content, allowed_mentions=allowed_mentions)
            return

        try:
            # Handle Threads
            target_channel = channel
            thread_obj = discord.utils.MISSING

            if isinstance(channel, discord.Thread):
                target_channel = channel.parent
                thread_obj = channel

            if not isinstance(target_channel, discord.TextChannel):
                await channel.send(content, allowed_mentions=allowed_mentions)
                return

            # Fetch or create webhook
            webhooks = await target_channel.webhooks()
            assert self.bot.user is not None
            webhook = next((w for w in webhooks if w.user and w.user.id == self.bot.user.id), None)

            if not webhook:
                webhook = await target_channel.create_webhook(name="UnicornAI Webhook")
            self._own_webhook_ids.add(webhook.id)
            self._seen_webhook_ids.add(webhook.id)

            # Send via webhook
            await webhook.send(
                content=content,
                username=persona.name,
                avatar_url=persona.avatar_url or self.bot.user.display_avatar.url,
                thread=thread_obj,
                allowed_mentions=allowed_mentions,
            )
        except Exception as e:
            log.error(f"Webhook send failed: {e}")
            # Fallback
            await channel.send(content, allowed_mentions=allowed_mentions)

    # --- Commands ---

    async def persona_autocomplete(self, interaction: discord.Interaction, current: str):
        """
        Autocomplete for summonable personas.
        Filters by 'allow_summon' flag.
        """
        try:
            # Run in thread to prevent blocking heartbeat during file I/O
            summonable_names = await asyncio.to_thread(self.personas.get_summonable_personas)

            choices = []
            for name in summonable_names:
                if current.lower() in name.lower():
                    choices.append(app_commands.Choice(name=name, value=name))

                if len(choices) >= 25:  # Discord limit
                    break

            return choices
        except Exception:
            # Silently fail autocomplete rather than spamming logs/console
            return []

    @commands.hybrid_command(name="summon", description="Summon a specific persona to chat.")
    @app_commands.describe(persona="The name of the persona to summon")
    @app_commands.autocomplete(persona=persona_autocomplete)
    @commands.guild_only()
    @commands.dynamic_cooldown(_summon_user_cd, commands.BucketType.user)  # pyright: ignore[reportArgumentType]
    @commands.dynamic_cooldown(_summon_channel_cd, commands.BucketType.channel)  # pyright: ignore[reportArgumentType]
    async def ai_summon(self, ctx: commands.Context, persona: str):
        """
        Summons a specific persona to the current channel.
        Usage: [p]summon <persona_name>
        """
        # 1. Validation: Persona Exists and is Summonable
        # We use asyncio.to_thread to avoid blocking event loop with I/O
        p_data = await asyncio.to_thread(self.personas.load_persona, persona)

        if not p_data:
            return await ctx.send(f"Persona `{persona}` not found.", ephemeral=True)

        if not p_data.allow_summon:
            # Security fail-safe: Even if they guessed the name, deny it.
            return await ctx.send(f"Persona `{persona}` cannot be summoned manually.", ephemeral=True)

        # 3. Trigger
        # Defer because API calls can take time
        await ctx.defer()

        try:
            # We pass the persona_override to _trigger_ai
            channel = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
            await self._trigger_ai(channel, ctx=ctx, persona_override=persona)
        except Exception as e:
            log.exception("Failed to summon persona")
            await ctx.send(f"Failed to summon persona: {e}")

    @commands.hybrid_command(name="aioptout", description="Toggle your opt-out status for the AI.")
    async def ai_optout(self, ctx: commands.Context):
        """
        Toggle your opt-out status.
        If opted out, your messages will be ignored by the AI context window.
        """
        current = await self.config.user(ctx.author).opt_out()
        new_state = not current
        await self.config.user(ctx.author).opt_out.set(new_state)

        if new_state:
            await ctx.send(
                "You have opted out. Your messages will no longer be included in the AI context.", ephemeral=True
            )
        else:
            await ctx.send("You have opted in. The AI can now see your messages.", ephemeral=True)

    @commands.group(name="ai")
    async def ai_group(self, ctx):
        """Manage UnicornAI settings."""
        pass

    @ai_group.command(name="toggle")
    @commands.is_owner()
    async def ai_toggle(self, ctx):
        """Toggle the auto-messaging loop for the current channel."""
        current = await self.config.channel(ctx.channel).enabled()
        new_state = not current
        await self.config.channel(ctx.channel).enabled.set(new_state)
        await ctx.send(f"UnicornAI is now {'**Enabled**' if new_state else '**Disabled**'} for {ctx.channel.mention}.")

    @ai_group.command(name="trigger")
    @commands.is_owner()
    async def ai_trigger(self, ctx, persona_name: str | None = None):
        """
        Manually trigger a generation cycle in this channel.
        Optionally provide a persona name to test specifically.
        """
        await self._trigger_ai(ctx=ctx, persona_override=persona_name)

    @ai_group.command(name="interval")
    @commands.is_owner()
    async def ai_interval(self, ctx, seconds: commands.Range[int, 60, 86400]):
        """Set the loop interval for this channel (seconds)."""
        await self.config.channel(ctx.channel).interval.set(seconds)
        await ctx.send(f"Interval set to {seconds} seconds for {ctx.channel.mention}.")

    @ai_group.command(name="history")
    @commands.is_owner()
    async def ai_history(self, ctx, limit: commands.Range[int, 1, 200]):
        """Set the global history limit (max messages to read)."""
        await self.config.history_limit.set(limit)
        await ctx.send(f"Global history limit set to {limit} messages.")

    @ai_group.command(name="endpoint", aliases=["openai_endpoint"])
    @commands.is_owner()
    async def ai_endpoint(self, ctx, url: str | None = None):
        """
        Set the OpenAI-compatible chat completions endpoint.

        A base URL such as `https://nano-gpt.com/api/v1` gets `/chat/completions` added.
        Leave empty to reset to NanoGPT.
        """
        if url is None:
            await self.config.openai_endpoint.clear()
            await ctx.send(f"Endpoint reset to `{DEFAULT_ENDPOINT}`.")
            return
        endpoint = normalize_endpoint(url)
        if endpoint is None:
            await ctx.send("The endpoint must be an `http://` or `https://` URL.")
            return
        await self.config.openai_endpoint.set(endpoint)
        await ctx.send(f"Endpoint set to `{endpoint}`.")

    @ai_group.command(name="model", aliases=["openai_model"])
    @commands.is_owner()
    async def ai_model(self, ctx, name: str):
        """Set the model name sent to the endpoint."""
        await self.config.openai_model.set(name)
        await ctx.send(f"Model set to `{name}`.")

    @ai_group.command(name="key", aliases=["openai_key"])
    @commands.is_owner()
    async def ai_key(self, ctx, api_key: str):
        """Set the endpoint's API key (stored as Red's `openai` API token)."""
        await self.bot.set_shared_api_tokens("openai", api_key=api_key)
        with contextlib.suppress(discord.HTTPException):
            await ctx.message.delete()
        await ctx.send("API key set successfully.")

    @ai_group.command(name="settings")
    @commands.is_owner()
    async def ai_settings(self, ctx):
        """Show the endpoint, model, and history settings."""
        settings = normalize_global_settings(await self.config.all())
        key_set = bool((await self.bot.get_shared_api_tokens("openai")).get("api_key"))
        await ctx.send(
            f"Endpoint: `{settings['openai_endpoint']}`\n"
            f"Model: `{settings['openai_model']}`\n"
            f"History limit: {settings['history_limit']}\n"
            f"API key: {'set' if key_set else 'not set'}"
        )

    @ai_group.group(name="persona")
    @commands.is_owner()
    async def persona_group(self, ctx):
        """Manage Personas."""
        pass

    @persona_group.command(name="list")
    async def persona_list(self, ctx):
        """List available personas."""
        personas = await asyncio.to_thread(self.personas.list_personas)
        if not personas:
            await ctx.send("No personas found in `data/personas/`.")
            return
        await ctx.send(f"Available Personas: {', '.join(personas)}")

    @persona_group.command(name="load")
    async def persona_load(self, ctx, name: str):
        """Load a persona for the current channel."""
        persona = await asyncio.to_thread(self.personas.load_persona, name)
        if persona:
            await self.config.channel(ctx.channel).active_persona.set(name)
            await ctx.send(f"Loaded persona **{persona.name}** for {ctx.channel.mention}.")
        else:
            await ctx.send(f"Could not find or load persona `{name}`.")
