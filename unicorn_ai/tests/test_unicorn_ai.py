"""Unit tests for the UnicornAI cog."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio
from redbot.core.bot import Red
from redbot.core.commands import Context

from unicorn_ai.openai import DEFAULT_ENDPOINT, DEFAULT_MODEL, AIRequestError
from unicorn_ai.persona import Persona
from unicorn_ai.unicorn_ai import (
    MAX_INTERVAL,
    UnicornAI,
    normalize_channel_settings,
    normalize_endpoint,
    normalize_global_settings,
    retry_delay,
)


@pytest.mark.parametrize("malformed", [None, [], "bad", 5])
def test_normalize_channel_settings_handles_malformed_shapes(malformed: object) -> None:
    assert normalize_channel_settings(malformed) == {
        "enabled": False,
        "interval": 300,
        "active_persona": None,
        "last_run": 0.0,
    }


def test_normalize_channel_settings_uses_strict_bool_and_bounds() -> None:
    settings = normalize_channel_settings(
        {"enabled": "false", "interval": 999999, "active_persona": [], "last_run": "nan"}
    )
    assert settings == {
        "enabled": False,
        "interval": 86400,
        "active_persona": None,
        "last_run": 0.0,
    }


def test_normalize_global_settings_bounds_history_and_defaults_to_nanogpt() -> None:
    settings = normalize_global_settings({"history_limit": 9999, "openai_endpoint": [], "openai_model": ""})
    assert settings == {
        "history_limit": 200,
        "openai_endpoint": "https://nano-gpt.com/api/v1/chat/completions",
        "openai_model": DEFAULT_MODEL,
    }
    assert DEFAULT_ENDPOINT == "https://nano-gpt.com/api/v1/chat/completions"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://nano-gpt.com/api/v1", "https://nano-gpt.com/api/v1/chat/completions"),
        ("https://openrouter.ai/api/v1/", "https://openrouter.ai/api/v1/chat/completions"),
        ("<https://x.test/v1/chat/completions>", "https://x.test/v1/chat/completions"),
        ("http://localhost:8080/v1", "http://localhost:8080/v1/chat/completions"),
        ("ftp://x.test/v1", None),
        ("nano-gpt.com/api/v1", None),
        ("https://", None),
    ],
)
def test_normalize_endpoint(url: str, expected: str | None) -> None:
    assert normalize_endpoint(url) == expected


def test_retry_delay_backs_off_and_caps() -> None:
    assert retry_delay(300, 0) == 300
    assert retry_delay(300, 1) == 300
    assert retry_delay(300, 2) == 600
    assert retry_delay(300, 3) == 1200
    assert retry_delay(300, 50) == 300 * 2**8
    assert retry_delay(3600, 50) == MAX_INTERVAL


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.user = MagicMock(spec=discord.ClientUser)
    bot.user.id = 999999
    bot.user.display_avatar = MagicMock()
    bot.user.display_avatar.url = "http://avatar.png"
    bot.owner_ids = {12345}
    bot.wait_until_ready = AsyncMock()

    # Mock for get_shared_api_tokens("openai")
    bot.get_shared_api_tokens = AsyncMock(return_value={"api_key": "test_key_123"})

    return bot


@pytest.fixture
def persona_mock() -> Persona:
    return Persona(
        name="Test",
        description="A test persona",
        system_prompt="You are a test.",
        avatar_url="http://test.png",
        history_limit=10,
        allow_summon=True,
    )


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock, persona_mock: Persona) -> UnicornAI:
    # Patch the loop start before initializing to prevent it from running during tests
    with patch("discord.ext.tasks.Loop.start"):
        cog_instance = UnicornAI(bot_mock)

    # Mock Config
    config_mock = MagicMock()

    # Channel Config
    channel_data = {
        "enabled": True,
        "interval": 300,
        "active_persona": "Test",
        "last_run": 0,
    }

    class ChannelConfigWrapper:
        def __init__(self, c_id):
            self.c_id = c_id
            self.last_run = MagicMock()
            self.last_run.set = AsyncMock()

        def all(self):
            class AllWrapper:
                def __await__(self):
                    async def _get():
                        return channel_data.copy()

                    return _get().__await__()

            return AllWrapper()

    config_mock.channel = MagicMock(side_effect=lambda c: ChannelConfigWrapper(c.id))

    class AllChannelsWrapper:
        def __await__(self):
            async def _get():
                return {888888: channel_data.copy()}

            return _get().__await__()

    config_mock.all_channels = MagicMock(return_value=AllChannelsWrapper())

    # Global Config
    global_data = {
        "history_limit": 50,
        "openai_endpoint": "https://api.example.test/v1/chat/completions",
        "openai_model": "test-model",
    }

    class GlobalAllWrapper:
        def __await__(self):
            async def _get():
                return global_data.copy()

            return _get().__await__()

    config_mock.all = MagicMock(return_value=GlobalAllWrapper())

    # User config (opt_out)
    class UserConfigWrapper:
        def opt_out(self):
            class OptOutWrapper:
                def __await__(self):
                    async def _get():
                        return False  # default false

                    return _get().__await__()

            return OptOutWrapper()

    config_mock.user = MagicMock(return_value=UserConfigWrapper())

    cog_instance.config = config_mock

    # Mock Client
    cog_instance.openai = MagicMock()
    cog_instance.openai.generate_response = AsyncMock(return_value="OpenAI response")

    # Mock Persona Manager
    cog_instance.personas = MagicMock()
    cog_instance.personas.load_persona = MagicMock(return_value=persona_mock)

    return cog_instance


@pytest.fixture
def ctx_mock() -> Context:
    ctx = MagicMock(spec=Context)
    ctx.channel = MagicMock(spec=discord.TextChannel)
    ctx.channel.id = 888888

    ctx.author = MagicMock(spec=discord.Member)
    ctx.author.id = 54321
    ctx.author.display_name = "User"

    ctx.send = AsyncMock()
    ctx.message = MagicMock(spec=discord.Message)
    ctx.message.delete = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_auto_message_loop(cog: UnicornAI, bot_mock: MagicMock) -> None:
    # Setup channel mock
    channel_mock = MagicMock(spec=discord.TextChannel)
    bot_mock.get_channel.return_value = channel_mock

    # Mock trigger logic with a real coroutine so task tracking is exercised.
    import asyncio

    cog._trigger_ai = AsyncMock()

    # Call the inner coroutine of the loop manually
    await cog.auto_message_loop.coro(cog)

    # Allow create_task to schedule and run
    await asyncio.sleep(0)

    # Verify trigger_ai was called because last_run=0 and now > interval(300)
    cog._trigger_ai.assert_called_once_with(channel=channel_mock)


@pytest.mark.asyncio
async def test_auto_message_loop_skips_if_not_interval(cog: UnicornAI, bot_mock: MagicMock) -> None:
    # Set last_run to now, so it shouldn't trigger
    # Config is mocked nicely, we can manipulate the dictionary being returned if we intercept it,
    # but let's just mock all_channels
    async def _get_channels():
        return {888888: {"enabled": True, "interval": 300, "active_persona": "Test", "last_run": time.time()}}

    class AllChannelsWrapper:
        def __await__(self):
            return _get_channels().__await__()

    cog.config.all_channels.return_value = AllChannelsWrapper()  # type: ignore

    cog._trigger_ai = AsyncMock()

    await cog.auto_message_loop.coro(cog)
    import asyncio

    await asyncio.sleep(0)

    cog._trigger_ai.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed", [None, [], "bad"])
async def test_auto_message_loop_survives_malformed_config_root(cog: UnicornAI, malformed: object) -> None:
    cog.config.all_channels = AsyncMock(return_value=malformed)
    cog._trigger_ai = AsyncMock()

    await cog.auto_message_loop.coro(cog)

    cog._trigger_ai.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_message_loop_does_not_treat_false_string_as_enabled(cog: UnicornAI) -> None:
    cog.config.all_channels = AsyncMock(return_value={888888: {"enabled": "false", "interval": 300, "last_run": 0}})
    cog._trigger_ai = AsyncMock()

    await cog.auto_message_loop.coro(cog)

    cog._trigger_ai.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_manual_overlap(cog: UnicornAI, bot_mock: MagicMock, ctx_mock: MagicMock) -> None:
    # Duplicate work for one channel is rejected rather than queued.
    event = asyncio.Event()
    call_count = 0

    async def fake_do_generate(*args, **kwargs) -> bool:
        nonlocal call_count
        call_count += 1
        await event.wait()
        return True

    cog._do_generate_and_send = fake_do_generate

    async def empty_history(*args, **kwargs):
        if False:
            yield None

    ctx_mock.channel.history = empty_history

    task1 = asyncio.create_task(cog._trigger_ai(channel=ctx_mock.channel))
    task2 = asyncio.create_task(cog._trigger_ai(ctx=ctx_mock))

    await asyncio.sleep(0.1)

    # Only 1 call should have progressed into the protected section
    assert call_count == 1

    event.set()
    await asyncio.gather(task1, task2)

    assert call_count == 1
    ctx_mock.send.assert_any_await("An AI response is already being generated for this channel.", ephemeral=True)


def _message(author_id: int, name: str, content: str, webhook_id: int | None = None) -> MagicMock:
    msg = MagicMock(spec=discord.Message)
    msg.author.id = webhook_id if webhook_id is not None else author_id
    msg.author.display_name = name
    msg.clean_content = content
    msg.webhook_id = webhook_id
    return msg


def _set_history(channel: MagicMock, *messages: MagicMock) -> None:
    """Channel history, given newest first as Discord returns it."""

    def history(*args, **kwargs):
        async def gen():
            for msg in messages:
                yield msg

        return gen()

    channel.history = MagicMock(side_effect=history)


@pytest.mark.asyncio
@patch("unicorn_ai.unicorn_ai.UnicornAI._send_response")
async def test_trigger_ai_builds_history_and_posts(
    send_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock, persona_mock: Persona
) -> None:
    _set_history(
        ctx_mock.channel,
        _message(999999, "Bot", "General Kenobi"),
        _message(54321, "User", "Hello there"),
    )

    await cog._trigger_ai(ctx=ctx_mock)

    ctx_mock.channel.history.assert_called_once_with(limit=10)

    openai_mock: MagicMock = cog.openai  # type: ignore
    openai_mock.generate_response.assert_called_once()
    kwargs = openai_mock.generate_response.call_args.kwargs
    assert kwargs["endpoint"] == "https://api.example.test/v1/chat/completions"
    assert kwargs["model"] == "test-model"
    assert kwargs["api_key"] == "test_key_123"
    assert kwargs["system_instruction"] == "You are a test."
    assert kwargs["history"] == [
        {"role": "user", "parts": [{"text": "User: Hello there"}]},
        {"role": "model", "parts": [{"text": "Bot: General Kenobi"}]},
    ]

    send_mock.assert_called_once_with(ctx_mock.channel, "OpenAI response", persona_mock)


# --- Persona messages sent through our webhook ---


OWN_WEBHOOK_ID = 7001
FOREIGN_WEBHOOK_ID = 7002


def _webhooks_channel(channel: MagicMock) -> AsyncMock:
    own = MagicMock(spec=discord.Webhook)
    own.id = OWN_WEBHOOK_ID
    own.user.id = 999999
    foreign = MagicMock(spec=discord.Webhook)
    foreign.id = FOREIGN_WEBHOOK_ID
    foreign.user.id = 123
    channel.guild = MagicMock(spec=discord.Guild)
    channel.permissions_for.return_value.manage_webhooks = True
    channel.webhooks = AsyncMock(return_value=[own, foreign])
    return channel.webhooks


@pytest.mark.asyncio
@patch("unicorn_ai.unicorn_ai.UnicornAI._send_response")
async def test_own_webhook_messages_are_the_personas_turns(
    send_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock
) -> None:
    _webhooks_channel(ctx_mock.channel)
    _set_history(
        ctx_mock.channel,
        _message(0, "Test", "I said this earlier", webhook_id=OWN_WEBHOOK_ID),
        _message(0, "Other Persona", "A different character spoke", webhook_id=OWN_WEBHOOK_ID),
        _message(0, "Proxied User", "Hi from PluralKit", webhook_id=FOREIGN_WEBHOOK_ID),
        _message(54321, "User", "Hello"),
    )

    await cog._trigger_ai(ctx=ctx_mock)

    history = cog.openai.generate_response.call_args.kwargs["history"]  # type: ignore[attr-defined]
    assert [(h["role"], h["parts"][0]["text"]) for h in history] == [
        ("user", "User: Hello"),
        ("user", "Proxied User: Hi from PluralKit"),
        ("user", "Other Persona: A different character spoke"),
        ("model", "Test: I said this earlier"),
    ]


@pytest.mark.asyncio
@patch("unicorn_ai.unicorn_ai.UnicornAI._send_response")
async def test_webhooks_are_looked_up_once(send_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock) -> None:
    webhooks = _webhooks_channel(ctx_mock.channel)
    _set_history(
        ctx_mock.channel,
        _message(0, "Test", "Mine", webhook_id=OWN_WEBHOOK_ID),
        _message(0, "Proxied User", "Theirs", webhook_id=FOREIGN_WEBHOOK_ID),
    )

    await cog._trigger_ai(ctx=ctx_mock)
    await cog._trigger_ai(ctx=ctx_mock)

    webhooks.assert_awaited_once()


# --- API errors ---


@pytest.mark.asyncio
@patch("unicorn_ai.unicorn_ai.UnicornAI._send_response")
async def test_scheduled_api_error_is_not_posted(send_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock) -> None:
    cog.openai.generate_response = AsyncMock(side_effect=AIRequestError("HTTP 401: Invalid API Key"))  # type: ignore[method-assign]
    _set_history(ctx_mock.channel, _message(54321, "User", "Hello"))

    await cog._trigger_ai(channel=ctx_mock.channel)

    send_mock.assert_not_called()
    assert cog._failures == {888888: 1}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("is_owner", "expected"), [(True, "The AI request failed: HTTP 401"), (False, "Check the bot logs")]
)
@patch("unicorn_ai.unicorn_ai.UnicornAI._send_response")
async def test_manual_api_error_goes_to_invoker_only(
    send_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock, bot_mock: MagicMock, is_owner: bool, expected: str
) -> None:
    bot_mock.is_owner = AsyncMock(return_value=is_owner)
    cog.openai.generate_response = AsyncMock(side_effect=AIRequestError("HTTP 401: Invalid API Key"))  # type: ignore[method-assign]
    _set_history(ctx_mock.channel, _message(54321, "User", "Hello"))

    await cog._trigger_ai(ctx=ctx_mock)

    send_mock.assert_not_called()
    assert expected in ctx_mock.send.await_args.args[0]
    assert cog._failures == {}


@pytest.mark.asyncio
@patch("unicorn_ai.unicorn_ai.UnicornAI._send_response")
async def test_missing_api_key_posts_nothing(
    send_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock, bot_mock: MagicMock
) -> None:
    bot_mock.get_shared_api_tokens = AsyncMock(return_value={})
    _set_history(ctx_mock.channel, _message(54321, "User", "Hello"))

    await cog._trigger_ai(channel=ctx_mock.channel)

    send_mock.assert_not_called()
    cog.openai.generate_response.assert_not_called()  # type: ignore[attr-defined]


# --- Retry backoff ---


def _channels(cog: UnicornAI, last_run: float, interval: int = 300) -> None:
    cog.config.all_channels = AsyncMock(  # type: ignore[method-assign]
        return_value={888888: {"enabled": True, "interval": interval, "active_persona": "Test", "last_run": last_run}}
    )


@pytest.mark.asyncio
async def test_failed_run_restarts_the_timer(cog: UnicornAI, bot_mock: MagicMock, ctx_mock: MagicMock) -> None:
    """A failed scheduled run restarts the timer instead of retrying on the next 60 second tick."""
    recorded: dict[str, float] = {}
    make_wrapper = cog.config.channel.side_effect  # type: ignore[attr-defined]

    def channel(c: object) -> object:
        wrapper = make_wrapper(c)
        wrapper.last_run.set = AsyncMock(side_effect=lambda value: recorded.__setitem__("last_run", value))
        return wrapper

    cog.config.channel.side_effect = channel  # type: ignore[attr-defined]
    cog.openai.generate_response = AsyncMock(side_effect=AIRequestError("boom"))  # type: ignore[method-assign]
    _set_history(ctx_mock.channel, _message(54321, "User", "Hello"))

    await cog._trigger_ai(channel=ctx_mock.channel)

    assert time.time() - recorded["last_run"] < 5
    bot_mock.get_channel.return_value = ctx_mock.channel
    cog._trigger_ai = AsyncMock()  # type: ignore[method-assign]
    _channels(cog, last_run=recorded["last_run"])

    await cog.auto_message_loop.coro(cog)
    await asyncio.sleep(0)

    cog._trigger_ai.assert_not_called()


@pytest.mark.asyncio
async def test_repeated_failures_back_off(cog: UnicornAI, bot_mock: MagicMock) -> None:
    bot_mock.get_channel.return_value = MagicMock(spec=discord.TextChannel)
    cog._trigger_ai = AsyncMock()  # type: ignore[method-assign]
    cog._failures[888888] = 3  # next attempt after 4 intervals

    _channels(cog, last_run=time.time() - 3 * 300)
    await cog.auto_message_loop.coro(cog)
    await asyncio.sleep(0)
    cog._trigger_ai.assert_not_called()

    _channels(cog, last_run=time.time() - 4 * 300)
    await cog.auto_message_loop.coro(cog)
    await asyncio.sleep(0)
    cog._trigger_ai.assert_called_once()


@pytest.mark.asyncio
@patch("unicorn_ai.unicorn_ai.UnicornAI._send_response")
async def test_success_resets_failures(send_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock) -> None:
    cog._failures[888888] = 5
    _set_history(ctx_mock.channel, _message(54321, "User", "Hello"))

    await cog._trigger_ai(channel=ctx_mock.channel)

    send_mock.assert_called_once()
    assert cog._failures == {}


# --- Settings commands ---


@pytest.mark.asyncio
async def test_endpoint_command(cog: UnicornAI, ctx_mock: MagicMock) -> None:
    cog.config.openai_endpoint.set = AsyncMock()  # type: ignore[attr-defined]
    cog.config.openai_endpoint.clear = AsyncMock()  # type: ignore[attr-defined]

    await getattr(UnicornAI.ai_endpoint, "callback")(cog, ctx_mock, "https://openrouter.ai/api/v1")  # noqa: B009
    cog.config.openai_endpoint.set.assert_awaited_once_with("https://openrouter.ai/api/v1/chat/completions")  # type: ignore[attr-defined]

    await getattr(UnicornAI.ai_endpoint, "callback")(cog, ctx_mock, "not a url")  # noqa: B009
    assert "must be an" in ctx_mock.send.await_args.args[0]
    cog.config.openai_endpoint.set.assert_awaited_once()  # type: ignore[attr-defined]

    await getattr(UnicornAI.ai_endpoint, "callback")(cog, ctx_mock, None)  # noqa: B009
    cog.config.openai_endpoint.clear.assert_awaited_once()  # type: ignore[attr-defined]
    assert "nano-gpt.com" in ctx_mock.send.await_args.args[0]


@pytest.mark.asyncio
async def test_key_command_deletes_the_message(cog: UnicornAI, ctx_mock: MagicMock, bot_mock: MagicMock) -> None:
    bot_mock.set_shared_api_tokens = AsyncMock()

    await getattr(UnicornAI.ai_key, "callback")(cog, ctx_mock, "sk-secret")  # noqa: B009

    bot_mock.set_shared_api_tokens.assert_awaited_once_with("openai", api_key="sk-secret")
    ctx_mock.message.delete.assert_awaited_once()


def test_vertex_commands_are_gone() -> None:
    names = {command.name for command in UnicornAI.ai_group.walk_commands()}
    assert {"setup", "provider"}.isdisjoint(names)
    assert {"endpoint", "model", "key", "settings"} <= names


@pytest.mark.asyncio
async def test_send_response_webhook(cog: UnicornAI) -> None:
    channel_mock = AsyncMock(spec=discord.TextChannel)
    guild_mock = MagicMock(spec=discord.Guild)
    channel_mock.guild = guild_mock

    perms = MagicMock()
    perms.manage_webhooks = True
    channel_mock.permissions_for.return_value = perms

    webhook_mock = AsyncMock(spec=discord.Webhook)
    webhook_mock.user.id = 999999
    channel_mock.webhooks.return_value = [webhook_mock]

    persona = MagicMock()
    persona.name = "Webhoo"
    persona.avatar_url = "http://w.com"

    await cog._send_response(channel_mock, "Test msg", persona)

    webhook_mock.send.assert_awaited_once()
    kwargs = webhook_mock.send.await_args.kwargs
    assert kwargs["content"] == "Test msg"
    assert kwargs["username"] == "Webhoo"
    assert kwargs["allowed_mentions"].everyone is False
    assert kwargs["allowed_mentions"].roles is False
    assert kwargs["allowed_mentions"].users is False
    channel_mock.send.assert_not_called()


@pytest.mark.asyncio
async def test_send_response_no_perms(cog: UnicornAI) -> None:
    channel_mock = AsyncMock(spec=discord.TextChannel)
    guild_mock = MagicMock(spec=discord.Guild)
    channel_mock.guild = guild_mock

    perms = MagicMock()
    perms.manage_webhooks = False
    channel_mock.permissions_for.return_value = perms

    await cog._send_response(channel_mock, "Test fallback", MagicMock())

    channel_mock.send.assert_awaited_once()
    assert channel_mock.send.await_args.args == ("Test fallback",)
    allowed_mentions = channel_mock.send.await_args.kwargs["allowed_mentions"]
    assert allowed_mentions.everyone is False
    assert allowed_mentions.roles is False
    assert allowed_mentions.users is False


@pytest.mark.asyncio
@patch("unicorn_ai.unicorn_ai.UnicornAI._trigger_ai")
async def test_summon_command(trigger_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock) -> None:
    # `summon` is a hybrid_command, so we get the callback like normal
    await getattr(UnicornAI.ai_summon, "callback")(cog, ctx_mock, "Test")  # noqa: B009

    # Verify persona was checked and trigger_ai called
    personas_mock: MagicMock = cog.personas  # type: ignore
    personas_mock.load_persona.assert_called_once_with("Test")
    trigger_mock.assert_called_once_with(ctx_mock.channel, ctx=ctx_mock, persona_override="Test")


@pytest.mark.asyncio
async def test_summon_command_not_allowed(cog: UnicornAI, ctx_mock: MagicMock) -> None:
    persona_mock = MagicMock()
    persona_mock.allow_summon = False
    personas_mock: MagicMock = cog.personas  # type: ignore
    personas_mock.load_persona.return_value = persona_mock

    cog._trigger_ai = AsyncMock()  # type: ignore

    await getattr(UnicornAI.ai_summon, "callback")(cog, ctx_mock, "Test")  # noqa: B009

    ctx_mock.send.assert_called_once_with("Persona `Test` cannot be summoned manually.", ephemeral=True)
    trigger_mock: AsyncMock = cog._trigger_ai  # type: ignore
    trigger_mock.assert_not_called()
