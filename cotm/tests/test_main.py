"""Integration and unit tests for ContestCog in cotm/main.py"""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import commands

from cotm import const
from cotm.main import ContestCog


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock) -> ContestCog:
    return ContestCog(bot_mock)


@pytest.fixture
def ctx_mock() -> MagicMock:
    ctx = MagicMock(spec=commands.Context)
    ctx.channel = MagicMock(spec=discord.TextChannel)
    ctx.channel.send = AsyncMock()
    ctx.send = AsyncMock()
    # async with ctx.typing() must work as an async context manager
    typing_cm = MagicMock()
    typing_cm.__aenter__ = AsyncMock(return_value=None)
    typing_cm.__aexit__ = AsyncMock(return_value=False)
    ctx.typing = MagicMock(return_value=typing_cm)
    return ctx


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_contest_info(cog: ContestCog, ctx_mock: MagicMock) -> None:
    cog._import_txt = MagicMock(return_value="test text")  # type: ignore[method-assign]
    cog._format_text = MagicMock(return_value="formatted text")  # type: ignore[method-assign]

    await cog.contest.callback(cog, ctx_mock, 5)  # type: ignore[arg-type]

    assert cog.contest_number == "5th"

    cast(AsyncMock, ctx_mock.channel.send).assert_called_once()
    _args, kwargs = ctx_mock.channel.send.call_args
    assert "view" in kwargs

    view = kwargs["view"]
    from cotm.cotm_views import ContestDashboardView

    assert isinstance(view, ContestDashboardView)
    assert view.texts["description"] == "formatted text"


@pytest.mark.asyncio
async def test_get_contest_results(cog: ContestCog) -> None:
    channel = MagicMock(spec=discord.TextChannel)

    msg1 = MagicMock(spec=discord.Message)
    # author must be a proper mock so str() returns a predictable string
    author_mock = MagicMock(spec=discord.Member)
    author_mock.__str__ = MagicMock(return_value="User1")
    msg1.author = author_mock

    react1 = MagicMock(spec=discord.Reaction)
    react1.emoji = const.COTM_VOTE_EMOJI

    user1 = MagicMock(spec=discord.Member)
    user1.joined_at = datetime.now(timezone.utc) - timedelta(days=10)
    user2 = MagicMock(spec=discord.Member)
    user2.joined_at = datetime.now(timezone.utc) - timedelta(days=2)

    async def get_users() -> AsyncGenerator[MagicMock, None]:
        yield user1
        yield user2

    react1.users.return_value = get_users()
    msg1.reactions = [react1]

    async def history(limit: int | None = None) -> AsyncGenerator[MagicMock, None]:
        yield msg1

    channel.history.return_value = history()

    # voter_server_age = 5 days: user1 (joined 10 days ago) is valid, user2 (joined 2 days ago) is not
    results = await cog._get_contest_results(
        channel, const.COTM_VOTE_EMOJI, timedelta(days=5)
    )

    assert len(results) == 1
    assert results[0]["name"] == "User1"
    assert results[0]["valid_votes"] == 1
    assert results[0]["invalid_votes"] == 1


@pytest.mark.asyncio
async def test_contestcount(cog: ContestCog, ctx_mock: MagicMock) -> None:
    channel_mock = MagicMock(spec=discord.TextChannel)
    channel_mock.mention = "#test-channel"

    cog._get_contest_results = AsyncMock(  # type: ignore[method-assign]
        return_value=[{"name": "User1", "valid_votes": 5, "invalid_votes": 1}]
    )

    await cog.contestcount.callback(
        cog,  # type: ignore[arg-type]
        ctx_mock,
        channel_mock,
        const.COTM_VOTE_EMOJI,
        False,
        None,
    )

    cast(AsyncMock, ctx_mock.channel.send).assert_called_once()
    _args, kwargs = ctx_mock.channel.send.call_args
    assert "view" in kwargs
    from cotm.cotm_views import StandingsView

    assert isinstance(kwargs["view"], StandingsView)


@pytest.mark.asyncio
async def test_cotmreward(
    cog: ContestCog, ctx_mock: MagicMock, bot_mock: MagicMock
) -> None:
    unicornia_mock = MagicMock()
    unicornia_mock.add_balance = AsyncMock(return_value=True)
    bot_mock.get_cog.return_value = unicornia_mock

    channel_mock = MagicMock(spec=discord.TextChannel)
    channel_mock.mention = "#test-channel"

    msg1 = MagicMock(spec=discord.Message)
    user_author = MagicMock(spec=discord.Member)
    user_author.id = 123
    user_author.__str__ = MagicMock(return_value="User1")
    msg1.author = user_author

    react1 = MagicMock(spec=discord.Reaction)
    react1.emoji = const.COTM_VOTE_EMOJI

    voter = MagicMock(spec=discord.Member)
    voter.joined_at = datetime.now(timezone.utc) - timedelta(days=10)

    async def get_users() -> AsyncGenerator[MagicMock, None]:
        yield voter

    react1.users.return_value = get_users()
    msg1.reactions = [react1]

    async def history(limit: int | None = None) -> AsyncGenerator[MagicMock, None]:
        yield msg1

    channel_mock.history.return_value = history()

    await cog.cotmreward.callback(
        cog,  # type: ignore[arg-type]
        ctx_mock,
        channel_mock,
    )

    unicornia_mock.add_balance.assert_called_once_with(
        user_id=123,
        amount=const.COTM_REWARDS[0],
        reason="COTM Top 10 Reward (Rank 1)",
        source="ContestCog",
    )

    cast(AsyncMock, ctx_mock.channel.send).assert_called_once()


# ---------------------------------------------------------------------------
# dpytest integration: verify the cog is loaded and bot responds to a message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dpytest_message_does_not_raise() -> None:
    """Sending a plain message through dpytest must not raise any errors.

    ContestCog has no on_message listener, but this confirms the cog attaches
    to the bot without breaking the event dispatch pipeline.

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

    cog = ContestCog(bot)  # type: ignore[arg-type]
    await bot.add_cog(cog)

    await dpytest.message("hello")
    await dpytest.run_all_events()
    await dpytest.empty_queue()
    # No exception means the cog attaches cleanly and event dispatch is intact.
