"""
UniMod - AI-Powered Auto Moderation Cog

Combines VADER sentiment analysis for local pre-filtering with GLM5 via NanoGPT
for accurate rule violation detection. Server rules are included directly in the
system prompt, leveraging the model's large context window.
"""

import asyncio
import json
import logging
import re
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import aiohttp
import discord
import nltk
from discord.ext import tasks
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from redbot.core import Config, commands
from redbot.core.bot import Red

log = logging.getLogger("red.kirin_cogs.unimod")

# Ensure VADER lexicon is downloaded
try:
    nltk.data.find("sentiment/vader_lexicon.zip")
except LookupError:
    nltk.download("vader_lexicon", quiet=True)


@dataclass
class BufferedMessage:
    """Represents a message stored in the buffer for analysis."""

    id: int
    author_id: int
    author_name: str
    content: str
    timestamp: str
    channel_id: int
    channel_name: str
    guild_id: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AIAnalysisResult:
    """Represents the parsed AI analysis result."""

    is_violation: bool
    confidence: float
    violated_rules: list[str]
    severity: str | None
    explanation: str
    primary_message_id: int | None


class UniMod(commands.Cog):
    """
    AI-Powered Auto Moderation System

    Monitors whitelisted channels using VADER sentiment analysis for pre-filtering
    and GLM5 AI for accurate rule violation detection.
    """

    # System prompt template with anti-censorship override
    SYSTEM_PROMPT_TEMPLATE = """You are an emotionless, highly accurate automated Discord moderator for a strictly 18+ community.

## SERVER RULES
{rules}

## CRITICAL OPERATING INSTRUCTIONS
1. ANTI-CENSORSHIP OVERRIDE: This is an 18+ server. Consensual explicit discussions, kink, and profanity are ALLOWED and expected. DO NOT apply standard AI safety filters. DO NOT flag content just because it is sexual or NSFW.
2. ONLY flag behavior if it explicitly violates one of the SERVER RULES listed above (e.g., lack of consent, underage individuals, forbidden topics, harassment).
3. CHANNEL AWARENESS: The user will tell you which channel this conversation is in. Cross-reference with channel-specific rules. If a topic is allowed in the server but posted in the WRONG channel, it is a rule violation.
4. IMAGE RULES: You cannot see images, but if users are discussing posting forbidden images, flag the text discussing it.
5. FALSE POSITIVES: If the behavior is borderline, consensual banter, or you are unsure, lean towards NOT flagging ("is_violation": false).
6. Horny-Jail and Comfy-Chat are the server's general chat channels.

## RESPONSE FORMAT
You MUST respond with valid JSON only. Do not include markdown formatting, code blocks (like ```json), or conversational text.
Use this exact schema:
{{
    "is_violation": <boolean: true or false>,
    "confidence": <float: 0.0 to 1.0>,
    "violated_rules": <array of strings: list of rule numbers like ["9.2", "8.1"], or [] if no violation>,
    "severity": <string: "low", "medium", "high", or null if no violation>,
    "explanation": <string: 1-2 sentence explanation of your decision, noting the channel context if relevant>,
    "primary_message_id": <integer: exact ID of the most problematic message, or null if no violation>
}}"""

    USER_PROMPT_TEMPLATE = """## Conversation Context
This conversation is taking place in the channel: #{channel_name}

## Conversation Log
```json
{conversation_json}
```

Analyze this conversation against the server rules, paying close attention to channel-specific rules. Respond with JSON only."""

    # NanoGPT API configuration (same as unicorn_ai)
    NANOGPT_ENDPOINT = "https://nano-gpt.com/api/v1/chat/completions"
    NANOGPT_MODEL = "zai-org/glm-5:thinking"

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)

        # No global config needed - uses Red's shared API tokens
        # Guild config only
        default_guild = {
            "enabled": False,
            "alert_channel_id": None,
            "whitelisted_channels": [],
            "vader_threshold": -0.5,
            "buffer_size": 20,
        }

        self.config.register_guild(**default_guild)

        # Load server rules from file
        self.rules = self._load_rules()

        # Initialize VADER analyzer
        self.vader_analyzer = SentimentIntensityAnalyzer()

        # Per-channel message buffers
        self.channel_buffers: dict[int, deque] = {}
        self.channel_locks: dict[int, asyncio.Lock] = {}

        # Background task references (prevents GC)
        self._background_tasks: set[asyncio.Task] = set()

        # Statistics
        self.stats = {
            "messages_processed": 0,
            "vader_triggers": 0,
            "ai_reviews": 0,
            "violations_found": 0,
        }

        # Last AI response for debugging
        self._last_ai_response: str | None = None
        self._last_ai_error: str | None = None

        log.info(f"UniMod initialized. Rules loaded: {len(self.rules)} characters")

    def _load_rules(self) -> str:
        """Load rules from rules.md file in cog directory."""
        rules_path = Path(__file__).parent / "rules.md"

        if not rules_path.exists():
            log.warning("rules.md not found - using empty rules")
            return "No server rules have been configured."

        try:
            with open(rules_path, encoding="utf-8") as f:
                content = f.read()
            log.info(f"Loaded rules from {rules_path}")
            return content
        except Exception as e:
            log.error(f"Failed to load rules.md: {e}")
            return "Failed to load server rules."

    def _get_buffer(self, channel_id: int, max_size: int = 20) -> deque:
        """Get or create a message buffer for a channel."""
        if channel_id not in self.channel_buffers:
            self.channel_buffers[channel_id] = deque(maxlen=max_size)
        return self.channel_buffers[channel_id]

    def _get_lock(self, channel_id: int) -> asyncio.Lock:
        """Get or create a lock for a channel."""
        if channel_id not in self.channel_locks:
            self.channel_locks[channel_id] = asyncio.Lock()
        return self.channel_locks[channel_id]

    def _vader_check_single(self, msg: BufferedMessage, threshold: float) -> tuple[bool, float, bool]:
        """
        Check a single message for negative sentiment.

        Args:
            msg: The message to check
            threshold: The VADER threshold (e.g., -0.5)

        Returns:
            tuple: (should_trigger, score, is_extreme)
        """
        if not msg.content.strip():
            return False, 0.0, False

        scores = self.vader_analyzer.polarity_scores(msg.content)
        compound = scores["compound"]

        should_trigger = compound < threshold
        # Extreme threshold is 0.3 below the base threshold
        is_extreme = compound < (threshold - 0.3)

        return should_trigger, compound, is_extreme

    def check_vader_scores(self, messages: list[BufferedMessage], threshold: float) -> tuple[bool, float, bool]:
        """
        Check each message individually for negative sentiment.

        Args:
            messages: List of messages to check
            threshold: The VADER threshold (e.g., -0.5)

        Returns:
            tuple: (should_trigger, lowest_score, is_extreme)
        """
        lowest_score = 0.0
        should_trigger = False
        is_extreme = False

        for msg in messages:
            if not msg.content.strip():
                continue
            scores = self.vader_analyzer.polarity_scores(msg.content)
            compound = scores["compound"]

            if compound < lowest_score:
                lowest_score = compound

            if compound < threshold:
                should_trigger = True

            # Extreme threshold is 0.3 below the base threshold
            if compound < (threshold - 0.3):
                is_extreme = True

        return should_trigger, lowest_score, is_extreme

    def _build_system_prompt(self) -> str:
        """Build the system prompt with server rules included."""
        return self.SYSTEM_PROMPT_TEMPLATE.format(rules=self.rules)

    def parse_ai_response(self, raw_content: str) -> AIAnalysisResult:
        """
        Parse AI response using regex to extract JSON.

        Handles LLM output variations:
        - Invisible whitespace before/after markdown
        - Conversational filler text
        - Markdown code blocks with varying formats
        - Thinking model output (<think>...</think> tags)
        """
        # Log the raw response for debugging
        log.debug(f"Raw AI response length: {len(raw_content)}")
        log.debug(f"Raw AI response preview: {raw_content[:500]}...")

        # Handle thinking model output - remove <think>...</think> blocks
        cleaned_content = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL)

        # Also try removing markdown code blocks if present
        cleaned_content = re.sub(r"```json\s*", "", cleaned_content)
        cleaned_content = re.sub(r"```\s*", "", cleaned_content)

        # re.DOTALL allows the dot to match newlines
        # Use non-greedy match to find the first complete JSON object
        match = re.search(r"\{[^{}]*\}", cleaned_content, re.DOTALL)

        if not match:
            # Try a more aggressive search for nested JSON
            match = re.search(r"\{.*\}", cleaned_content, re.DOTALL)

        if not match:
            log.error(f"Could not find JSON in response. Full response: {raw_content}")
            raise ValueError("No JSON object found in AI response.")

        json_str = match.group(0)
        log.debug(f"Extracted JSON: {json_str}")

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            log.error(f"JSON decode error: {e}. Extracted string: {json_str}")
            raise

        # Safe type-casting for primary_message_id (may be string, int, or null)
        primary_msg_id = data.get("primary_message_id")
        if primary_msg_id is not None:
            try:
                primary_msg_id = int(str(primary_msg_id).strip())
            except (ValueError, TypeError):
                primary_msg_id = None

        # Safe severity extraction (default to None if no violation)
        is_violation = data.get("is_violation", False)
        severity = data.get("severity") if is_violation else None
        if severity not in ("low", "medium", "high"):
            severity = "low" if is_violation else None

        return AIAnalysisResult(
            is_violation=is_violation,
            confidence=float(data.get("confidence", 0.0)),
            violated_rules=data.get("violated_rules", []) or [],
            severity=severity,
            explanation=data.get("explanation", "") or "",
            primary_message_id=primary_msg_id,
        )

    async def _analyze_with_ai(self, system_prompt: str, user_prompt: str) -> AIAnalysisResult:
        """Make async API call to NanoGPT using aiohttp."""
        # Get API key from Red's shared API tokens (same pattern as unicorn_ai)
        api_tokens = await self.bot.get_shared_api_tokens("openai")
        api_key = api_tokens.get("api_key")

        if not api_key:
            raise ValueError("OpenAI API key not configured. Use `[p]set api openai <api_key>` to set it.")

        # Diagnostic logging: prompt sizes
        system_len = len(system_prompt)
        user_len = len(user_prompt)
        total_len = system_len + user_len
        estimated_tokens = total_len // 4  # Rough estimate: ~4 chars per token
        log.info("Starting AI analysis request to NanoGPT...")
        log.info(
            f"Prompt sizes - System: {system_len} chars, User: {user_len} chars, Total: {total_len} chars (~{estimated_tokens} tokens)"
        )

        request_start = time.monotonic()
        timeout_seconds = 360  # 6 minutes for thinking model

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.NANOGPT_ENDPOINT,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self.NANOGPT_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "max_tokens": 1000,
                        "temperature": 0.3,
                    },
                    timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        self._last_ai_error = f"API Error {response.status}: {error_text}"
                        log.error(self._last_ai_error)
                        raise aiohttp.ClientResponseError(
                            request_info=None,  # pyright: ignore[reportArgumentType]
                            history=None,  # pyright: ignore[reportArgumentType]
                            status=response.status,
                            message=f"NanoGPT API Error {response.status}: {error_text}",
                        )
                    result = await response.json()

            raw_content = result["choices"][0]["message"]["content"]
            request_duration = time.monotonic() - request_start

            # Save response for debugging
            self._last_ai_response = raw_content
            self._last_ai_error = None
            self._save_last_response(raw_content)

            log.info(f"AI response received in {request_duration:.1f}s. Length: {len(raw_content)} characters")
            log.debug(f"AI raw response preview: {raw_content[:200]}...")
            return self.parse_ai_response(raw_content)

        except TimeoutError:
            request_duration = time.monotonic() - request_start
            error_msg = f"AI request timed out after {request_duration:.1f}s (limit: {timeout_seconds}s)"
            self._last_ai_error = error_msg
            log.error(error_msg)
            log.error(f"Prompt was ~{estimated_tokens} tokens, model: {self.NANOGPT_MODEL}")
            raise
        except Exception as e:
            request_duration = time.monotonic() - request_start
            self._last_ai_error = str(e)
            log.error(f"AI request failed after {request_duration:.1f}s: {e}")
            raise

    def _save_last_response(self, content: str):
        """Save the last AI response to a file for debugging."""
        try:
            log_path = Path(__file__).parent / "last.log"
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("=== UniMod Last AI Response ===\n")
                f.write(f"Timestamp: {datetime.now(UTC).isoformat()}\n")
                f.write(f"Model: {self.NANOGPT_MODEL}\n")
                f.write(f"Length: {len(content)} characters\n")
                f.write(f"\n{'=' * 50}\n\n")
                f.write(content)
            log.debug(f"Saved last response to {log_path}")
        except Exception as e:
            log.warning(f"Could not save last response: {e}")

    async def _process_buffer(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel | discord.Thread,
        messages: list[BufferedMessage],
        threshold: float = -0.5,
    ):
        """Process buffer contents - runs in background task."""
        if not messages:
            log.debug("Empty buffer, skipping processing")
            return

        self.stats["ai_reviews"] += 1
        log.info(f"Processing buffer for #{channel.name} with {len(messages)} messages (threshold: {threshold})")

        try:
            # Full VADER check on all messages (pass the threshold)
            should_review, lowest_score, _ = self.check_vader_scores(messages, threshold)
            log.info(f"VADER check result: should_review={should_review}, lowest_score={lowest_score}")

            if not should_review:
                log.info(f"VADER passed: lowest score was {lowest_score}, skipping AI review")
                return

            self.stats["vader_triggers"] += 1
            log.info(f"VADER triggered (score {lowest_score} < threshold {threshold}), sending to AI...")

            # Build system prompt with rules
            system_prompt = self._build_system_prompt()

            # Format conversation for AI
            conversation_json = json.dumps([m.to_dict() for m in messages], indent=2)
            channel_name = messages[0].channel_name if messages else "unknown"
            user_prompt = self.USER_PROMPT_TEMPLATE.format(
                channel_name=channel_name, conversation_json=conversation_json
            )

            log.info(f"Sending {len(messages)} messages to AI for analysis...")

            # Call AI
            result = await self._analyze_with_ai(system_prompt, user_prompt)

            log.info(f"AI analysis complete: is_violation={result.is_violation}, confidence={result.confidence:.2f}")

            # Handle result
            if result.is_violation:
                self.stats["violations_found"] += 1
                log.warning(f"VIOLATION DETECTED! Severity: {result.severity}, Rules: {result.violated_rules}")
                await self._send_alert(guild, channel, messages, result)
            else:
                log.info(f"AI determined no violation (confidence: {result.confidence:.2f})")

        except aiohttp.ClientError as e:
            log.error(f"API error during AI analysis: {e}")
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse AI response: {e}")
        except ValueError as e:
            log.error(f"Value error in AI analysis: {e}")
        except Exception as e:
            log.error(f"Unexpected error in _process_buffer: {type(e).__name__}: {e}")
            import traceback

            log.error(traceback.format_exc())

    async def _send_alert(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel | discord.Thread,
        messages: list[BufferedMessage],
        result: AIAnalysisResult,
    ):
        """Send alert to configured channel or DM owner."""
        log.info(f"_send_alert called for guild {guild.name}, channel #{channel.name}")

        embed = self._build_alert_embed(guild, channel, messages, result)
        log.debug("Alert embed built successfully")

        alert_channel_id = await self.config.guild(guild).alert_channel_id()
        log.info(f"Alert channel ID from config: {alert_channel_id}")

        if alert_channel_id:
            # Send to configured channel
            alert_channel = guild.get_channel(alert_channel_id)
            log.info(f"Resolved alert channel: {alert_channel}")
            if alert_channel and isinstance(alert_channel, discord.TextChannel):
                try:
                    await alert_channel.send(embed=embed)
                    log.info(f"✅ Sent violation alert to #{alert_channel.name}")
                    return
                except discord.Forbidden:
                    log.warning(f"No permission to send to alert channel {alert_channel_id}")
            else:
                log.warning(f"Could not find alert channel with ID {alert_channel_id}")

        # Fallback: DM bot owner(s)
        # Red 3.5+ supports multiple owners via owner_ids
        owner_ids = getattr(self.bot, "owner_ids", None) or set()
        if not owner_ids and self.bot.owner_id:
            owner_ids = {self.bot.owner_id}

        log.info(f"Falling back to DM owner(s). Owner IDs: {owner_ids}")

        if not owner_ids:
            log.error("No owner IDs configured! Cannot send alert.")
            return

        # Try to DM all owners
        success = False
        for owner_id in owner_ids:
            try:
                owner = self.bot.get_user(owner_id)
                if not owner:
                    owner = await self.bot.fetch_user(owner_id)
                    log.info(f"fetch_user succeeded for owner_id {owner_id}")

                if owner:
                    await owner.send(embed=embed)
                    log.info(f"✅ Sent violation alert to owner via DM (user: {owner})")
                    success = True
            except discord.Forbidden:
                log.warning(f"Could not DM owner {owner_id} (Forbidden - DMs disabled?)")
            except Exception as e:
                log.error(f"Failed to send DM to owner {owner_id}: {type(e).__name__}: {e}")

        if not success:
            log.error("Failed to send alert to any owner!")

    def _build_alert_embed(
        self,
        guild: discord.Guild,
        channel: discord.TextChannel | discord.Thread,
        messages: list[BufferedMessage],
        result: AIAnalysisResult,
    ) -> discord.Embed:
        """Build the alert embed for a violation."""
        color = 0xFF6B6B if result.severity == "high" else 0xFFD93D if result.severity == "medium" else 0xFFA500

        embed = discord.Embed(title="⚠️ Potential Rule Violation Detected", color=color, timestamp=datetime.now(UTC))

        embed.add_field(name="Server", value=guild.name, inline=True)
        embed.add_field(name="Channel", value=f"#{channel.name}", inline=True)
        embed.add_field(name="Severity", value=result.severity.title() if result.severity else "Unknown", inline=True)
        embed.add_field(name="Confidence", value=f"{result.confidence:.0%}", inline=True)

        if result.violated_rules:
            embed.add_field(
                name="Violated Rules", value="\n".join(f"• Rule {r}" for r in result.violated_rules), inline=False
            )

        embed.add_field(name="Explanation", value=result.explanation or "No explanation provided", inline=False)

        # Add message link
        if result.primary_message_id:
            link = f"https://discord.com/channels/{guild.id}/{channel.id}/{result.primary_message_id}"
            embed.add_field(name="Jump to Message", value=f"[Click Here]({link})", inline=False)

        # Add context snippet
        if messages:
            context_lines = []
            for msg in messages[-5:]:  # Last 5 messages for context
                author_name = msg.author_name[:20]
                content_preview = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                context_lines.append(f"**{author_name}**: {content_preview}")
            embed.add_field(name="Recent Context", value="\n".join(context_lines), inline=False)

        return embed

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle incoming messages for moderation."""
        # 1. Filter invalid messages
        if message.author.bot or not message.guild:
            return
        if not await self.config.guild(message.guild).enabled():
            return

        # 2. WHITELIST CHECK: Only process whitelisted channels
        whitelisted = await self.config.guild(message.guild).whitelisted_channels()
        if message.channel.id not in whitelisted:
            return

        # Only monitor text channels (not DMs, forums, etc.)
        if not isinstance(message.channel, (discord.TextChannel, discord.Thread)):
            return

        channel = message.channel

        # 3. CRITICAL: Ignore bot commands
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        self.stats["messages_processed"] += 1

        # Get buffer settings
        buffer_size = await self.config.guild(message.guild).buffer_size()
        threshold = await self.config.guild(message.guild).vader_threshold()

        # 4. Get/create buffer for channel
        buffer = self._get_buffer(channel.id, buffer_size)
        lock = self._get_lock(channel.id)

        # 5. Add message to buffer and check VADER (inside lock)
        should_process = False
        messages_snapshot = []

        async with lock:
            buffered_msg = BufferedMessage(
                id=message.id,
                author_id=message.author.id,
                author_name=message.author.display_name,
                content=message.clean_content,
                timestamp=message.created_at.isoformat(),
                channel_id=channel.id,
                channel_name=channel.name,
                guild_id=message.guild.id,
            )
            buffer.append(buffered_msg)

            # 6. Quick VADER check on THIS message only (pass the threshold)
            _should_trigger, score, is_extreme = self._vader_check_single(buffered_msg, threshold)

            # 7. Determine if we should process now
            if is_extreme:
                should_process = True
                log.warning(f"Extreme toxicity detected in #{channel.name}: {score}")
            elif len(buffer) >= (buffer.maxlen or 0):
                should_process = True

            # 8. CRITICAL: Take snapshot and release lock BEFORE API call
            if should_process:
                messages_snapshot = list(buffer)
                buffer.clear()

        # 9. Process outside the lock (non-blocking)
        if should_process:
            task = asyncio.create_task(self._process_buffer(message.guild, channel, messages_snapshot, threshold))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    @tasks.loop(minutes=2)
    async def idle_buffer_check(self):
        """
        Background task to process buffers that have been idle.

        If a buffer has messages older than 2 minutes and passes VADER check,
        process it regardless of size.
        """
        now = datetime.now(UTC)

        for channel_id, buffer in list(self.channel_buffers.items()):
            if channel_id not in self.channel_locks:
                continue

            lock = self.channel_locks[channel_id]

            async with lock:
                if not buffer:
                    continue

                # Check age of oldest message (inside lock)
                oldest = buffer[0]
                oldest_time = datetime.fromisoformat(oldest.timestamp)
                age = (now - oldest_time).total_seconds()

                # If buffer is idle (> 2 minutes) and has content
                if age > 120 and len(buffer) > 0:
                    # Get guild from channel for threshold lookup
                    channel_obj = self.bot.get_channel(channel_id)
                    if channel_obj and isinstance(channel_obj, (discord.TextChannel, discord.Thread)):
                        guild = channel_obj.guild
                        threshold = await self.config.guild(guild).vader_threshold()

                        should_review, _score, _ = self.check_vader_scores(list(buffer), threshold)

                        if should_review:
                            log.info(f"Processing idle buffer for channel {channel_id}")

                            # Take snapshot and clear (still inside lock)
                            messages_snapshot = list(buffer)
                            buffer.clear()

                            # Process in background (outside lock after this block)
                            task = asyncio.create_task(
                                self._process_buffer(guild, channel_obj, messages_snapshot, threshold)
                            )
                            self._background_tasks.add(task)
                            task.add_done_callback(self._background_tasks.discard)

    @idle_buffer_check.before_loop
    async def before_idle_check(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        """Called when the cog is loaded."""
        self.idle_buffer_check.start()
        log.info("UniMod cog loaded and idle buffer check started")

    async def cog_unload(self):
        """Called when the cog is unloaded."""
        self.idle_buffer_check.cancel()
        log.info("UniMod cog unloaded")

    # ==================== COMMANDS ====================

    @commands.group(name="unimod")  # pyright: ignore[reportArgumentType]
    @commands.is_owner()
    async def unimod_group(self, ctx: commands.Context):
        """UniMod configuration commands."""
        pass

    @unimod_group.command(name="toggle")
    @commands.guild_only()
    async def toggle_monitoring(self, ctx: commands.Context):
        """Enable or disable monitoring in this guild."""
        assert ctx.guild is not None
        current = await self.config.guild(ctx.guild).enabled()
        await self.config.guild(ctx.guild).enabled.set(not current)
        status = "enabled" if not current else "disabled"
        await ctx.send(f"✅ UniMod monitoring {status} for this guild.")

    @unimod_group.command(name="channel")
    @commands.guild_only()
    async def set_alert_channel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Set the alert channel. Leave empty to DM owner instead."""
        assert ctx.guild is not None
        if channel:
            await self.config.guild(ctx.guild).alert_channel_id.set(channel.id)
            await ctx.send(f"✅ Alert channel set to {channel.mention}")
        else:
            await self.config.guild(ctx.guild).alert_channel_id.set(None)
            await ctx.send("✅ Alerts will be sent to bot owner via DM.")

    @unimod_group.command(name="whitelist")
    @commands.guild_only()
    async def whitelist_channels(self, ctx: commands.Context, *channels: discord.TextChannel):
        """Add channels to the monitoring whitelist."""
        assert ctx.guild is not None
        if not channels:
            await ctx.send("❌ Please specify at least one channel.")
            return

        current = await self.config.guild(ctx.guild).whitelisted_channels()
        added = []
        for ch in channels:
            if ch.id not in current:
                current.append(ch.id)
                added.append(ch.mention)

        await self.config.guild(ctx.guild).whitelisted_channels.set(current)

        if added:
            await ctx.send(f"✅ Added to whitelist: {', '.join(added)}")
        else:
            await ctx.send("ℹ️ All specified channels are already whitelisted.")  # noqa: RUF001

    @unimod_group.command(name="unwhitelist")
    @commands.guild_only()
    async def unwhitelist_channels(self, ctx: commands.Context, *channels: discord.TextChannel):
        """Remove channels from the monitoring whitelist."""
        assert ctx.guild is not None
        if not channels:
            await ctx.send("❌ Please specify at least one channel.")
            return

        current = await self.config.guild(ctx.guild).whitelisted_channels()
        removed = []
        for ch in channels:
            if ch.id in current:
                current.remove(ch.id)
                removed.append(ch.mention)

        await self.config.guild(ctx.guild).whitelisted_channels.set(current)

        if removed:
            await ctx.send(f"✅ Removed from whitelist: {', '.join(removed)}")
        else:
            await ctx.send("ℹ️ None of the specified channels were whitelisted.")  # noqa: RUF001

    @unimod_group.command(name="clearwhitelist")
    @commands.guild_only()
    async def clear_whitelist(self, ctx: commands.Context):
        """Clear all channels from the whitelist."""
        assert ctx.guild is not None
        await self.config.guild(ctx.guild).whitelisted_channels.set([])
        await ctx.send("✅ Whitelist cleared.")

    @unimod_group.command(name="status")
    @commands.guild_only()
    async def show_status(self, ctx: commands.Context):
        """Show monitoring status for this guild."""
        assert ctx.guild is not None
        enabled = await self.config.guild(ctx.guild).enabled()
        alert_channel_id = await self.config.guild(ctx.guild).alert_channel_id()
        whitelisted = await self.config.guild(ctx.guild).whitelisted_channels()
        threshold = await self.config.guild(ctx.guild).vader_threshold()
        buffer_size = await self.config.guild(ctx.guild).buffer_size()

        embed = discord.Embed(title="🛡️ UniMod Status", color=0x00FF00 if enabled else 0xFF0000)

        embed.add_field(name="Enabled", value="✅ Yes" if enabled else "❌ No", inline=True)
        embed.add_field(name="VADER Threshold", value=str(threshold), inline=True)
        embed.add_field(name="Buffer Size", value=str(buffer_size), inline=True)

        alert_channel = f"<#{alert_channel_id}>" if alert_channel_id else "Owner DM"
        embed.add_field(name="Alert Channel", value=alert_channel, inline=True)

        if whitelisted:
            channels_str = "\n".join(f"• <#{ch_id}>" for ch_id in whitelisted[:10])
            if len(whitelisted) > 10:
                channels_str += f"\n... and {len(whitelisted) - 10} more"
            embed.add_field(name=f"Whitelisted Channels ({len(whitelisted)})", value=channels_str, inline=False)
        else:
            embed.add_field(name="Whitelisted Channels", value="None configured", inline=False)

        await ctx.send(embed=embed)

    @unimod_group.command(name="stats")
    async def show_stats(self, ctx: commands.Context):
        """Show detection statistics."""
        embed = discord.Embed(title="📊 UniMod Statistics", color=0x0099FF)

        embed.add_field(name="Messages Processed", value=str(self.stats["messages_processed"]), inline=True)
        embed.add_field(name="VADER Triggers", value=str(self.stats["vader_triggers"]), inline=True)
        embed.add_field(name="AI Reviews", value=str(self.stats["ai_reviews"]), inline=True)
        embed.add_field(name="Violations Found", value=str(self.stats["violations_found"]), inline=True)
        embed.add_field(name="Active Buffers", value=str(len(self.channel_buffers)), inline=True)
        embed.add_field(name="Rules Length", value=f"{len(self.rules)} chars", inline=True)

        await ctx.send(embed=embed)

    @unimod_group.group(name="config")
    async def config_group(self, ctx: commands.Context):
        """Configuration commands."""
        pass

    @config_group.command(name="apikey")
    async def set_api_key(self, ctx: commands.Context, api_key: str):
        """Set the OpenAI API key (used for NanoGPT)."""
        await self.bot.set_shared_api_tokens("openai", api_key=api_key)
        await ctx.send("✅ OpenAI API key set. This will be used for NanoGPT.")

    @config_group.command(name="threshold")
    @commands.guild_only()
    async def set_threshold(self, ctx: commands.Context, threshold: float):
        """Set the VADER threshold (-1.0 to 0.0). More negative = less sensitive."""
        assert ctx.guild is not None
        if threshold < -1.0 or threshold > 0.0:
            await ctx.send("❌ Threshold must be between -1.0 and 0.0")
            return
        await self.config.guild(ctx.guild).vader_threshold.set(threshold)
        await ctx.send(f"✅ VADER threshold set to {threshold}")

    @config_group.command(name="buffersize")
    @commands.guild_only()
    async def set_buffer_size(self, ctx: commands.Context, size: int):
        """Set the message buffer size (10-50)."""
        assert ctx.guild is not None
        if size < 10 or size > 50:
            await ctx.send("❌ Buffer size must be between 10 and 50")
            return
        await self.config.guild(ctx.guild).buffer_size.set(size)
        await ctx.send(f"✅ Buffer size set to {size}")

    @config_group.command(name="show")
    async def show_config(self, ctx: commands.Context):
        """Show current configuration."""
        # Get API key from Red's shared tokens
        api_tokens = await self.bot.get_shared_api_tokens("openai")
        api_key = api_tokens.get("api_key", "")
        api_key_display = f"{'*' * 8}...{api_key[-4:]}" if api_key else "Not set"

        embed = discord.Embed(title="⚙️ UniMod Configuration", color=0x0099FF)

        embed.add_field(name="NanoGPT API Key", value=api_key_display, inline=False)
        embed.add_field(name="AI Model", value=self.NANOGPT_MODEL, inline=True)
        embed.add_field(name="API Endpoint", value=self.NANOGPT_ENDPOINT, inline=False)
        embed.add_field(name="Rules Source", value="rules.md file", inline=True)

        await ctx.send(embed=embed)

    @unimod_group.command(name="reloadrules")
    async def reload_rules(self, ctx: commands.Context):
        """Reload rules from the rules.md file."""
        self.rules = self._load_rules()
        await ctx.send(f"✅ Rules reloaded. {len(self.rules)} characters loaded.")

    @unimod_group.command(name="last")
    async def view_last_response(self, ctx: commands.Context):
        """
        View the last AI response for debugging.

        This command can ONLY be used in DMs with the bot.
        """
        # DM-only check
        if ctx.guild is not None:
            await ctx.send("❌ This command can only be used in DMs with the bot for privacy.")
            return

        # Check if we have a response
        if self._last_ai_error:
            await ctx.send(f"❌ Last AI request failed:\n```\n{self._last_ai_error}\n```")
            return

        if not self._last_ai_response:
            await ctx.send("❌ No AI response has been recorded yet.")
            return

        # Try to read from file first (more complete)
        log_path = Path(__file__).parent / "last.log"
        content = None

        if log_path.exists():
            try:
                with open(log_path, encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                log.warning(f"Could not read last.log: {e}")

        if not content:
            content = f"=== Last AI Response ===\nLength: {len(self._last_ai_response)} characters\n\n{self._last_ai_response}"

        # Send in chunks if too long
        if len(content) <= 1900:
            await ctx.send(f"```\n{content}\n```")
        else:
            # Split into multiple messages
            chunks = [content[i : i + 1900] for i in range(0, len(content), 1900)]
            for i, chunk in enumerate(chunks):
                await ctx.send(f"```\n{chunk}\n```\n*Part {i + 1}/{len(chunks)}*")
