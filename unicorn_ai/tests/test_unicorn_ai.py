"""Unit tests for the UnicornAI cog."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio
from redbot.core.bot import Red
from redbot.core.commands import Context

from unicorn_ai.persona import Persona
from unicorn_ai.unicorn_ai import UnicornAI


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
        personality="Testy",
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
        "provider": "vertex",
        "model": "gemini-test",
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
                        return False # default false
                    return _get().__await__()
            return OptOutWrapper()

    config_mock.user = MagicMock(return_value=UserConfigWrapper())

    cog_instance.config = config_mock

    # Mock Clients
    cog_instance.vertex = MagicMock()
    cog_instance.vertex.generate_response = AsyncMock(return_value="Vertex response")

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
    return ctx


@pytest.mark.asyncio
async def test_auto_message_loop(cog: UnicornAI, bot_mock: MagicMock) -> None:
    # Setup channel mock
    channel_mock = MagicMock(spec=discord.TextChannel)
    bot_mock.get_channel.return_value = channel_mock

    # Mock trigger logic
    cog._trigger_ai = AsyncMock()

    # Call the inner coroutine of the loop manually
    await cog.auto_message_loop.coro(cog)

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

    cog._trigger_ai.assert_not_called()


@pytest.mark.asyncio
@patch("unicorn_ai.unicorn_ai.UnicornAI._send_response")
async def test_trigger_ai_vertex(
    send_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock, persona_mock: Persona
) -> None:
    # Setup history
    msg_user = MagicMock(spec=discord.Message)
    msg_user.author.id = 54321
    msg_user.author.display_name = "User"
    msg_user.clean_content = "Hello there"

    msg_bot = MagicMock(spec=discord.Message)
    msg_bot.author.id = 999999
    msg_bot.author.display_name = "Bot"
    msg_bot.clean_content = "General Kenobi"

    async def history_gen(*args, **kwargs):
        yield msg_user
        yield msg_bot

    ctx_mock.channel.history = MagicMock(return_value=history_gen())

    # Run
    await cog._trigger_ai(ctx=ctx_mock)

    # Verify history limit and order
    ctx_mock.channel.history.assert_called_once_with(limit=10)

    # Verify vertex provider was called
    vertex_mock: MagicMock = cog.vertex  # type: ignore
    vertex_mock.generate_response.assert_called_once()
    _, kwargs = vertex_mock.generate_response.call_args
    assert kwargs["system_instruction"] == "You are a test."

    history = kwargs["history"]
    assert len(history) == 2
    # Because reverse() is called, bot comes first (since it was yielded second)
    assert history[0] == {"role": "model", "parts": [{"text": "Bot: General Kenobi"}]}
    assert history[1] == {"role": "user", "parts": [{"text": "User: Hello there"}]}

    # Verify response was sent
    send_mock.assert_called_once_with(ctx_mock.channel, "Vertex response", persona_mock)


@pytest.mark.asyncio
@patch("unicorn_ai.unicorn_ai.UnicornAI._send_response")
async def test_trigger_ai_openai(
    send_mock: AsyncMock, cog: UnicornAI, ctx_mock: MagicMock
) -> None:
    # Switch global settings to use OpenAI
    async def _get_global():
        return {"history_limit": 50, "provider": "openai", "openai_model": "gpt-4"}

    class GlobalWrapper:
        def __await__(self):
            return _get_global().__await__()

    cog.config.all.return_value = GlobalWrapper()  # type: ignore

    async def history_gen(*args, **kwargs):
        yield MagicMock(spec=discord.Message)

    ctx_mock.channel.history = MagicMock(return_value=history_gen())

    # Run
    await cog._trigger_ai(ctx=ctx_mock)

    # Verify openai client used
    openai_mock: MagicMock = cog.openai  # type: ignore
    vertex_mock: MagicMock = cog.vertex  # type: ignore
    openai_mock.generate_response.assert_called_once()
    vertex_mock.generate_response.assert_not_called()


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

    webhook_mock.send.assert_called_once_with(
        content="Test msg",
        username="Webhoo",
        avatar_url="http://w.com",
        thread=discord.utils.MISSING
    )
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

    channel_mock.send.assert_called_once_with("Test fallback")


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
