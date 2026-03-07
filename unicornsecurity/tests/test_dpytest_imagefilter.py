"""dpytest integration tests for unicornsecurity imagefilter."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config

from unicornsecurity.imagefilter import ImageFilter

TARGET_CHANNEL_ID = 1319688029530492948


@pytest.fixture
def config_mock_with_channel(target_id: int = TARGET_CHANNEL_ID) -> MagicMock:
    config = MagicMock(spec=Config)

    def _guild(*args: object, **kwargs: object) -> object:
        class _Group:
            def __getattr__(self, name: str) -> AsyncMock:
                if name == "target_channel_id":
                    am = AsyncMock(return_value=target_id)
                    am.set = AsyncMock()
                    return am
                am = AsyncMock(return_value=None)
                am.set = AsyncMock()
                return am

        return _Group()

    config.guild.side_effect = _guild
    return config


@pytest_asyncio.fixture
async def bot_and_cog(
    config_mock_with_channel: MagicMock,
) -> AsyncGenerator[tuple[dpy_commands.Bot, ImageFilter], None]:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    intents.message_content = True

    real_bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await real_bot._async_setup_hook()  # type: ignore[attr-defined]

    with patch("unicornsecurity.imagefilter.Config.get_conf", return_value=config_mock_with_channel):
        cog = ImageFilter(real_bot)
    cog.config = config_mock_with_channel

    dpytest.configure(real_bot)
    await real_bot.add_cog(cog)

    yield real_bot, cog

    await dpytest.empty_queue()


# --- on_message: ignore bots ---


@pytest.mark.asyncio
async def test_on_message_ignores_bots(bot_and_cog: tuple[dpy_commands.Bot, ImageFilter]) -> None:
    """Bot messages in the target channel should not trigger deletion."""
    real_bot, _cog = bot_and_cog
    guild = dpytest.get_config().guilds[0]
    channel = dpytest.get_config().channels[0]

    # Use MagicMock message so delete can be an AsyncMock
    msg = MagicMock()
    msg.author.bot = True
    msg.guild = guild
    msg.channel = channel
    msg.channel.id = channel.id
    msg.attachments = []
    msg.content = "https://example.com/pic.png"
    msg.delete = AsyncMock()

    real_bot.dispatch("message", msg)
    await dpytest.run_all_events()

    msg.delete.assert_not_called()


# --- on_message: ignore other channel ---


@pytest.mark.asyncio
async def test_on_message_ignores_non_target_channel(
    bot_and_cog: tuple[dpy_commands.Bot, ImageFilter],
) -> None:
    """Messages in non-target channels are not deleted."""
    real_bot, _cog = bot_and_cog
    guild = dpytest.get_config().guilds[0]
    channel = dpytest.get_config().channels[0]

    # Ensure channel id != TARGET_CHANNEL_ID
    assert channel.id != TARGET_CHANNEL_ID

    msg = MagicMock()
    msg.author.bot = False
    msg.guild = guild
    msg.channel = channel
    msg.channel.id = channel.id  # different from TARGET_CHANNEL_ID
    msg.attachments = []
    msg.content = "https://example.com/pic.png"
    msg.delete = AsyncMock()

    real_bot.dispatch("message", msg)
    await dpytest.run_all_events()

    msg.delete.assert_not_called()


# --- imagefilter setchannel ---


@pytest.mark.asyncio
async def test_setchannel_command(bot_and_cog: tuple[dpy_commands.Bot, ImageFilter]) -> None:
    """setchannel saves the channel id and sends confirmation."""
    _, cog = bot_and_cog
    guild = dpytest.get_config().guilds[0]
    channel = dpytest.get_config().channels[0]

    ctx = MagicMock()
    ctx.guild = guild
    ctx.channel = channel
    ctx.send = AsyncMock()

    await cog.set_filter_channel(ctx, channel)  # type: ignore[arg-type]

    ctx.send.assert_called_once()
    sent: str = ctx.send.call_args[0][0]
    assert "monitor" in sent.lower() or channel.mention in sent


# --- on_message: tenor allowed ---


@pytest.mark.asyncio
async def test_on_message_allows_tenor(bot_and_cog: tuple[dpy_commands.Bot, ImageFilter]) -> None:
    """Tenor URLs should NOT be deleted even in target channel."""
    real_bot, cog = bot_and_cog
    guild = dpytest.get_config().guilds[0]
    channel = dpytest.get_config().channels[0]

    # Patch config to treat channel as target
    def _guild(*args: object, **kwargs: object) -> object:
        class _Group:
            def __getattr__(self, name: str) -> AsyncMock:
                if name == "target_channel_id":
                    return AsyncMock(return_value=channel.id)
                return AsyncMock(return_value=None)

        return _Group()

    cog.config.guild.side_effect = _guild  # pyright: ignore[reportAttributeAccessIssue]

    msg = MagicMock()
    msg.author.bot = False
    msg.guild = guild
    msg.channel = channel
    msg.channel.id = channel.id
    msg.attachments = []
    msg.content = "https://tenor.com/view/something-gif-12345"
    msg.delete = AsyncMock()

    real_bot.dispatch("message", msg)
    await dpytest.run_all_events()

    msg.delete.assert_not_called()
