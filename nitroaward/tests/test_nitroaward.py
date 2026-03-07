"""Tests for the NitroAward cog.

Unit tests (pytest-asyncio) cover the core processing logic with mocked
dependencies. dpytest integration tests cover the on_member_update listener
dispatched through a real bot event loop.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config

from nitroaward.nitroaward import AWARD_AMOUNT, NitroAward

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_config_mock(last_boost_timestamp: float | None = None) -> MagicMock:
    """Return a Config mock whose user group returns ``last_boost_timestamp``."""
    config = MagicMock(spec=Config)
    user_group = MagicMock()
    user_group.last_boost_timestamp = AsyncMock(return_value=last_boost_timestamp)
    user_group.last_boost_timestamp.set = AsyncMock()
    config.user.return_value = user_group
    return config


def _make_member(
    user_id: int = 1,
    premium_since: datetime | None = None,
    display_name: str = "TestUser",
) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.display_name = display_name
    member.premium_since = premium_since
    return member


# ---------------------------------------------------------------------------
# Unit tests — process_boost_reward
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_boost_reward_awards_currency_on_first_boost() -> None:
    """Currency is awarded when premium_since is new (no prior timestamp stored)."""
    bot = MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)

    config = _make_config_mock(last_boost_timestamp=None)
    cog.config = config

    unicornia = MagicMock()
    unicornia.add_balance = AsyncMock(return_value=True)
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    unicornia.add_balance.assert_awaited_once_with(
        user_id=member.id,
        amount=AWARD_AMOUNT,
        reason="Nitro Boost Reward",
        source="NitroAward",
    )
    config.user(member).last_boost_timestamp.set.assert_awaited_once_with(ts.timestamp())


@pytest.mark.asyncio
async def test_process_boost_reward_skips_duplicate_boost() -> None:
    """Currency is NOT awarded when the stored timestamp matches the current boost."""
    bot = MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)

    # Stored timestamp matches current — already awarded
    config = _make_config_mock(last_boost_timestamp=ts.timestamp())
    cog.config = config

    unicornia = MagicMock()
    unicornia.add_balance = AsyncMock(return_value=True)
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    unicornia.add_balance.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_boost_reward_skips_when_premium_since_none() -> None:
    """If premium_since is None (boost revoked by the time we check), do nothing."""
    bot = MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()

    member = _make_member(premium_since=None)
    config = _make_config_mock(last_boost_timestamp=None)
    cog.config = config

    unicornia = MagicMock()
    unicornia.add_balance = AsyncMock(return_value=True)
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    unicornia.add_balance.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_boost_reward_logs_warning_when_unicornia_missing() -> None:
    """If Unicornia cog is absent, no exception is raised and nothing is awarded."""
    bot = MagicMock()
    bot.get_cog.return_value = None  # Unicornia not loaded

    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()

    ts = datetime(2024, 3, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)
    config = _make_config_mock(last_boost_timestamp=None)
    cog.config = config

    # Should complete without raising
    await cog.process_boost_reward(member)

    config.user(member).last_boost_timestamp.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_boost_reward_handles_add_balance_failure() -> None:
    """If add_balance returns False, the timestamp is NOT persisted."""
    bot = MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()

    ts = datetime(2024, 6, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)
    config = _make_config_mock(last_boost_timestamp=None)
    cog.config = config

    unicornia = MagicMock()
    unicornia.add_balance = AsyncMock(return_value=False)
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    config.user(member).last_boost_timestamp.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_boost_reward_handles_exception_from_unicornia() -> None:
    """Exceptions raised by add_balance are caught and do not propagate."""
    bot = MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()

    ts = datetime(2024, 9, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)
    config = _make_config_mock(last_boost_timestamp=None)
    cog.config = config

    unicornia = MagicMock()
    unicornia.add_balance = AsyncMock(side_effect=RuntimeError("DB error"))
    bot.get_cog.return_value = unicornia

    # Must not raise
    await cog.process_boost_reward(member)


# ---------------------------------------------------------------------------
# Unit tests — on_member_update guard logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_member_update_ignores_non_boost_changes() -> None:
    """on_member_update does nothing when premium_since didn't change from None."""
    bot = MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()
    cog.config = _make_config_mock()
    cog.process_boost_reward = AsyncMock()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    before = _make_member(premium_since=ts)  # was already boosting
    after = _make_member(premium_since=ts)  # still boosting — no change

    await cog.on_member_update(before, after)

    cog.process_boost_reward.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_member_update_ignores_boost_end() -> None:
    """on_member_update does nothing when a boost is removed (after.premium_since is None)."""
    bot = MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()
    cog.config = _make_config_mock()
    cog.process_boost_reward = AsyncMock()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    before = _make_member(premium_since=ts)
    after = _make_member(premium_since=None)  # boost ended

    await cog.on_member_update(before, after)

    cog.process_boost_reward.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_member_update_triggers_reward_on_new_boost() -> None:
    """on_member_update calls process_boost_reward when before=None, after=boosting."""
    bot = MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()
    cog.config = _make_config_mock()
    cog.process_boost_reward = AsyncMock()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    before = _make_member(premium_since=None)
    after = _make_member(premium_since=ts)

    await cog.on_member_update(before, after)

    cog.process_boost_reward.assert_awaited_once_with(after)


@pytest.mark.asyncio
async def test_on_member_update_prevents_concurrent_processing() -> None:
    """A second concurrent on_member_update for the same user is silently dropped."""
    bot = MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_users = set()
    cog.config = _make_config_mock()
    cog.process_boost_reward = AsyncMock()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    before = _make_member(user_id=42, premium_since=None)
    after = _make_member(user_id=42, premium_since=ts)

    # Simulate the user already being processed
    cog.processing_users.add(after.id)

    await cog.on_member_update(before, after)

    cog.process_boost_reward.assert_not_awaited()


# ---------------------------------------------------------------------------
# dpytest integration tests — on_member_update via bot event dispatch
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def bot() -> AsyncGenerator[dpy_commands.Bot, None]:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True

    real_bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await real_bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(real_bot)

    yield real_bot

    await dpytest.empty_queue()


@pytest.mark.asyncio
async def test_dpytest_member_update_new_boost_calls_process_reward(
    bot: dpy_commands.Bot,
) -> None:
    """Dispatching member_update with a new premium_since calls process_boost_reward."""
    with patch("nitroaward.nitroaward.Config.get_conf", return_value=_make_config_mock()):
        cog = NitroAward(bot)  # type: ignore[arg-type]

    cog.process_boost_reward = AsyncMock()
    await bot.add_cog(cog)

    guild = dpytest.get_config().guilds[0]
    member = guild.members[0]

    # Build before/after mocks with the transition we want to test
    before = MagicMock(spec=discord.Member)
    before.premium_since = None
    before.id = member.id

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    after = MagicMock(spec=discord.Member)
    after.premium_since = ts
    after.id = member.id

    bot.dispatch("member_update", before, after)
    await dpytest.run_all_events()

    # Drain any tasks spawned inside handlers
    pending = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    cog.process_boost_reward.assert_awaited_once_with(after)


@pytest.mark.asyncio
async def test_dpytest_member_update_no_boost_does_not_call_process_reward(
    bot: dpy_commands.Bot,
) -> None:
    """Dispatching member_update with no boost change does NOT call process_boost_reward."""
    with patch("nitroaward.nitroaward.Config.get_conf", return_value=_make_config_mock()):
        cog = NitroAward(bot)  # type: ignore[arg-type]

    cog.process_boost_reward = AsyncMock()
    await bot.add_cog(cog)

    ts = datetime(2024, 1, 1, tzinfo=UTC)

    before = MagicMock(spec=discord.Member)
    before.premium_since = ts
    before.id = 99

    after = MagicMock(spec=discord.Member)
    after.premium_since = ts  # unchanged — no new boost
    after.id = 99

    bot.dispatch("member_update", before, after)
    await dpytest.run_all_events()

    pending = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    cog.process_boost_reward.assert_not_awaited()
