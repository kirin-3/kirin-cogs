"""Unit, async, and dpytest integration tests for the Confess cog."""

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config
from redbot.core.bot import Red

from confess.confess import CONFESSION_CHANNEL_ID, Confess


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.owner_ids = {111}
    bot.add_view = MagicMock()
    return bot


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.sticky_message_id = AsyncMock(return_value=None)
    config.sticky_message_id.set = AsyncMock()
    return config


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock, config_mock: MagicMock) -> Confess:
    with patch("confess.confess.Config.get_conf", return_value=config_mock):
        c = Confess(bot_mock)
    c.config = config_mock
    return c


# ---------------------------------------------------------------------------
# get_confession_channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_confession_channel_returns_text_channel(
    cog: Confess, bot_mock: MagicMock
) -> None:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = CONFESSION_CHANNEL_ID
    bot_mock.get_channel.return_value = channel

    result = await cog.get_confession_channel()
    assert result is channel


@pytest.mark.asyncio
async def test_get_confession_channel_returns_none_for_non_text(
    cog: Confess, bot_mock: MagicMock
) -> None:
    bot_mock.get_channel.return_value = MagicMock(spec=discord.VoiceChannel)
    result = await cog.get_confession_channel()
    assert result is None


@pytest.mark.asyncio
async def test_get_confession_channel_returns_none_when_missing(
    cog: Confess, bot_mock: MagicMock
) -> None:
    bot_mock.get_channel.return_value = None
    result = await cog.get_confession_channel()
    assert result is None


# ---------------------------------------------------------------------------
# process_confession
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_confession_no_channel(cog: Confess) -> None:
    cog.get_confession_channel = AsyncMock(return_value=None)  # type: ignore[method-assign]

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.send_message = AsyncMock()

    await cog.process_confession(interaction, "test confession")

    interaction.response.send_message.assert_called_once_with(
        "Confession channel not found.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_process_confession_success(cog: Confess, bot_mock: MagicMock) -> None:
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "confessions"
    channel.id = CONFESSION_CHANNEL_ID
    channel.send = AsyncMock()

    cog.get_confession_channel = AsyncMock(return_value=channel)  # type: ignore[method-assign]
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    owner = MagicMock(spec=discord.User)
    owner.send = AsyncMock()
    bot_mock.fetch_user = AsyncMock(return_value=owner)

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.send_message = AsyncMock()
    interaction.user = MagicMock(spec=discord.Member)
    interaction.user.id = 999
    interaction.user.display_avatar.url = "https://example.com/avatar.png"

    await cog.process_confession(interaction, "I ate the last cookie")

    # Verify content format: must include the confession text, the Anonymous prefix,
    # the block-quote marker, and use allowed_mentions=none to prevent pings.
    channel.send.assert_called_once()
    _args, kwargs = channel.send.call_args
    sent_content: str = kwargs.get("content", "")
    assert "**Anonymous Confession**" in sent_content
    assert ">>>" in sent_content
    assert "I ate the last cookie" in sent_content
    # AllowedMentions has no __eq__, so compare the fields that matter
    am: discord.AllowedMentions = kwargs.get("allowed_mentions")
    assert am.everyone is False
    assert am.users is False
    assert am.roles is False

    # User got ephemeral confirmation
    interaction.response.send_message.assert_called_once_with(
        "Your confession has been sent, you are forgiven now.", ephemeral=True
    )

    # Owner was DMed with a log embed
    owner.send.assert_called_once()
    _args2, owner_kwargs = owner.send.call_args
    assert "embed" in owner_kwargs

    # Sticky was reposted
    cast(AsyncMock, cog._maybe_repost_sticky).assert_called_once_with(channel)


@pytest.mark.asyncio
async def test_process_confession_forbidden(cog: Confess, bot_mock: MagicMock) -> None:
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "confessions"
    channel.id = CONFESSION_CHANNEL_ID
    channel.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perm"))

    cog.get_confession_channel = AsyncMock(return_value=channel)  # type: ignore[method-assign]

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.send_message = AsyncMock()
    interaction.user = MagicMock(spec=discord.Member)

    await cog.process_confession(interaction, "a secret")

    interaction.response.send_message.assert_called_once_with(
        "I don't have permission to send messages to the confession room.",
        ephemeral=True,
    )


@pytest.mark.asyncio
async def test_process_confession_generic_error(cog: Confess) -> None:
    channel = MagicMock(spec=discord.TextChannel)
    channel.name = "confessions"
    channel.id = CONFESSION_CHANNEL_ID
    channel.send = AsyncMock(side_effect=Exception("unexpected"))

    cog.get_confession_channel = AsyncMock(return_value=channel)  # type: ignore[method-assign]

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response.send_message = AsyncMock()
    interaction.user = MagicMock(spec=discord.Member)

    await cog.process_confession(interaction, "a confession")

    interaction.response.send_message.assert_called_once_with(
        "Something went wrong.", ephemeral=True
    )


# ---------------------------------------------------------------------------
# on_message listener — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_message_ignores_bots(cog: Confess) -> None:
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = True
    message.guild = MagicMock()

    await cog.on_message(message)
    cast(AsyncMock, cog._maybe_repost_sticky).assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_non_guild(cog: Confess) -> None:
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = False
    message.guild = None

    await cog.on_message(message)
    cast(AsyncMock, cog._maybe_repost_sticky).assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_wrong_channel(cog: Confess) -> None:
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 12345  # not the confession channel

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = False
    message.guild = MagicMock()
    message.channel = channel

    await cog.on_message(message)
    cast(AsyncMock, cog._maybe_repost_sticky).assert_not_called()


@pytest.mark.asyncio
async def test_on_message_reposts_sticky_in_confession_channel(cog: Confess) -> None:
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = CONFESSION_CHANNEL_ID

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = False
    message.guild = MagicMock()
    message.channel = channel

    await cog.on_message(message)
    cast(AsyncMock, cog._maybe_repost_sticky).assert_called_once_with(
        channel, responding_to_message=message
    )


# ---------------------------------------------------------------------------
# on_message — dpytest integration: event fired through real dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dpytest_on_message_calls_maybe_repost_sticky() -> None:
    """dpytest dispatches a real on_message event; cog must route it to _maybe_repost_sticky
    only when the channel id matches CONFESSION_CHANNEL_ID.
    The dpytest channel id won't match, so _maybe_repost_sticky must NOT be called.

    Bot, cog, and dpytest setup are done inline to avoid fixture-scoping issues
    with dpytest's module-level _cur_config global state.
    """
    intents = discord.Intents.default()
    intents.members = True  # required for member cache so dpytest.message() works
    intents.messages = True
    intents.message_content = True
    intents.guilds = True

    bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(bot)

    config_mock: MagicMock = MagicMock(spec=Config)
    config_mock.sticky_message_id = AsyncMock(return_value=None)

    with patch("confess.confess.Config.get_conf", return_value=config_mock):
        cog = Confess(bot)  # type: ignore[arg-type]
    cog.config = config_mock
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]
    await bot.add_cog(cog)

    # Send a message through dpytest — channel id won't match CONFESSION_CHANNEL_ID
    await dpytest.message("hello world")
    await dpytest.run_all_events()
    await dpytest.empty_queue()

    # _maybe_repost_sticky must NOT be called for a non-confession channel
    cast(AsyncMock, cog._maybe_repost_sticky).assert_not_called()


# ---------------------------------------------------------------------------
# on_raw_message_delete listener
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raw_message_delete_ignores_wrong_channel(cog: Confess) -> None:
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    payload = MagicMock(spec=discord.RawMessageDeleteEvent)
    payload.channel_id = 99999
    payload.message_id = 123

    await cog.on_raw_message_delete(payload)
    cast(AsyncMock, cog._maybe_repost_sticky).assert_not_called()


@pytest.mark.asyncio
async def test_raw_message_delete_ignores_non_sticky_message(
    cog: Confess, config_mock: MagicMock
) -> None:
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]
    config_mock.sticky_message_id = AsyncMock(return_value=555)

    payload = MagicMock(spec=discord.RawMessageDeleteEvent)
    payload.channel_id = CONFESSION_CHANNEL_ID
    payload.message_id = 999  # different message — not the sticky

    await cog.on_raw_message_delete(payload)
    cast(AsyncMock, cog._maybe_repost_sticky).assert_not_called()


@pytest.mark.asyncio
async def test_raw_message_delete_reposts_when_sticky_is_deleted(
    cog: Confess, config_mock: MagicMock, bot_mock: MagicMock
) -> None:
    sticky_id = 555
    config_mock.sticky_message_id = AsyncMock(return_value=sticky_id)
    cog._maybe_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = CONFESSION_CHANNEL_ID
    bot_mock.get_channel.return_value = channel

    payload = MagicMock(spec=discord.RawMessageDeleteEvent)
    payload.channel_id = CONFESSION_CHANNEL_ID
    payload.message_id = sticky_id  # the sticky itself was deleted

    await cog.on_raw_message_delete(payload)
    cast(AsyncMock, cog._maybe_repost_sticky).assert_called_once_with(channel)


# ---------------------------------------------------------------------------
# _maybe_repost_sticky internal logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_repost_sticky_no_existing_sticky_posts(
    cog: Confess, config_mock: MagicMock
) -> None:
    """When no sticky exists yet, _do_repost_sticky is called for the confession channel."""
    config_mock.sticky_message_id = AsyncMock(return_value=None)
    cog._do_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = CONFESSION_CHANNEL_ID

    await cog._maybe_repost_sticky(channel)

    cast(AsyncMock, cog._do_repost_sticky).assert_called_once()


@pytest.mark.asyncio
async def test_maybe_repost_sticky_skips_when_sticky_is_last_message(
    cog: Confess, config_mock: MagicMock
) -> None:
    """When the sticky message is already the last message, no repost happens."""
    sticky_id = 123456789
    config_mock.sticky_message_id = AsyncMock(return_value=sticky_id)
    cog._do_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = CONFESSION_CHANNEL_ID
    # Simulate the sticky being the last message in the channel
    channel.last_message_id = sticky_id

    await cog._maybe_repost_sticky(channel)

    cast(AsyncMock, cog._do_repost_sticky).assert_not_called()


@pytest.mark.asyncio
async def test_maybe_repost_sticky_skips_responding_message_is_sticky(
    cog: Confess, config_mock: MagicMock
) -> None:
    """When the message triggering the repost IS the sticky itself, skip reposting."""
    sticky_id = 999
    config_mock.sticky_message_id = AsyncMock(return_value=sticky_id)
    cog._do_repost_sticky = AsyncMock()  # type: ignore[method-assign]

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = CONFESSION_CHANNEL_ID
    channel.last_message_id = sticky_id + 1  # something else is last

    responding_message = MagicMock(spec=discord.Message)
    responding_message.id = sticky_id  # the responding message IS the sticky
    responding_message.created_at = discord.utils.snowflake_time(sticky_id)

    await cog._maybe_repost_sticky(channel, responding_to_message=responding_message)

    cast(AsyncMock, cog._do_repost_sticky).assert_not_called()
