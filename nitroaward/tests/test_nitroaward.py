"""Tests for the NitroAward cog.

Unit tests (pytest-asyncio) cover the core processing logic with mocked
dependencies. dpytest integration tests cover the on_member_update listener
dispatched through a real bot event loop.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config

from nitroaward.nitroaward import AWARD_AMOUNT, NitroAward

GUILD_ID = 1234

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_config_mock(
    last_boost_timestamp: float | None = None,
    legacy_records: dict | None = None,
) -> MagicMock:
    """Return a Config mock with member scope and global legacy records."""
    config = MagicMock(spec=Config)

    member_group = MagicMock()
    member_group.last_boost_timestamp = AsyncMock(return_value=last_boost_timestamp)
    member_group.last_boost_timestamp.set = AsyncMock()
    config.member.return_value = member_group

    config.schema_version = AsyncMock(return_value=2)
    config.schema_version.set = AsyncMock()
    config.all_users = AsyncMock(return_value={})
    config.legacy_boost_records = AsyncMock(return_value=dict(legacy_records or {}))
    config.legacy_boost_records.set = AsyncMock()
    config.all_members = AsyncMock(return_value={GUILD_ID: {1: {"last_boost_timestamp": 1.0}}})
    member_from_ids = MagicMock()
    member_from_ids.clear = AsyncMock()
    config.member_from_ids.return_value = member_from_ids
    legacy_user = MagicMock()
    legacy_user.clear = AsyncMock()
    config.user_from_id.return_value = legacy_user
    return config


def _make_member(
    user_id: int = 1,
    premium_since: datetime | None = None,
    display_name: str = "TestUser",
    guild_id: int = GUILD_ID,
) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.display_name = display_name
    member.premium_since = premium_since
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    member.guild = guild
    return member


def _make_cog(bot: MagicMock | None = None, config: MagicMock | None = None) -> NitroAward:
    bot = bot or MagicMock()
    cog = NitroAward.__new__(NitroAward)
    cog.bot = bot
    cog.processing_members = set()
    cog.config = config or _make_config_mock()
    return cog


def _outcome(state: str = "settled") -> SimpleNamespace:
    return SimpleNamespace(state=state, new_balance=AWARD_AMOUNT, amount=AWARD_AMOUNT, result={})


@pytest.mark.asyncio
async def test_deletion_clears_member_migration_copy_and_original_user_scope() -> None:
    config = _make_config_mock(legacy_records={"1": 1.0})
    cog = _make_cog(config=config)

    await cog.red_delete_data_for_user(requester="user", user_id=1)

    config.member_from_ids(GUILD_ID, 1).clear.assert_awaited_once()
    config.legacy_boost_records.set.assert_awaited_once_with({})
    config.user_from_id(1).clear.assert_awaited_once()


# ---------------------------------------------------------------------------
# Unit tests — process_boost_reward
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_boost_reward_awards_currency_on_first_boost() -> None:
    """Currency is awarded through the idempotent operation API with a stable key."""
    bot = MagicMock()
    config = _make_config_mock(last_boost_timestamp=None)
    cog = _make_cog(bot, config)

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=_outcome("settled"))
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    expected_key = f"nitro:{GUILD_ID}:{member.id}:{ts.timestamp()}"
    unicornia.apply_operation.assert_awaited_once_with(
        key=expected_key,
        user_id=member.id,
        amount=AWARD_AMOUNT,
        direction="credit",
        source="nitroaward",
        guild_id=GUILD_ID,
        reason="Nitro Boost Reward",
    )
    config.member(member).last_boost_timestamp.set.assert_awaited_once_with(ts.timestamp())


@pytest.mark.asyncio
async def test_process_boost_reward_skips_duplicate_boost() -> None:
    """Currency is NOT awarded when the stored member timestamp matches."""
    bot = MagicMock()
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    config = _make_config_mock(last_boost_timestamp=ts.timestamp())
    cog = _make_cog(bot, config)

    member = _make_member(premium_since=ts)

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=_outcome("settled"))
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    unicornia.apply_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_boost_reward_duplicate_outcome_marks_completion() -> None:
    """Crash-window retry: a duplicate settlement still records local completion."""
    bot = MagicMock()
    config = _make_config_mock(last_boost_timestamp=None)
    cog = _make_cog(bot, config)

    ts = datetime(2024, 2, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)

    unicornia = MagicMock()
    # Unicornia committed earlier, our Config write was lost to a crash.
    unicornia.apply_operation = AsyncMock(return_value=_outcome("duplicate"))
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    config.member(member).last_boost_timestamp.set.assert_awaited_once_with(ts.timestamp())


@pytest.mark.asyncio
async def test_process_boost_reward_legacy_record_suppresses_exact_event() -> None:
    """A legacy global record for the same boost event suppresses re-award and is adopted."""
    bot = MagicMock()
    ts = datetime(2024, 3, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)
    config = _make_config_mock(last_boost_timestamp=None, legacy_records={str(member.id): ts.timestamp()})
    cog = _make_cog(bot, config)

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=_outcome("settled"))
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    unicornia.apply_operation.assert_not_awaited()
    # Adopted into guild/member scope so the legacy record is consulted once.
    config.member(member).last_boost_timestamp.set.assert_awaited_once_with(ts.timestamp())


@pytest.mark.asyncio
async def test_process_boost_reward_legacy_record_does_not_suppress_new_event() -> None:
    """A legacy record for a *different* boost event must not suppress a new boost."""
    bot = MagicMock()
    member = _make_member(premium_since=datetime(2024, 5, 1, tzinfo=UTC))
    old_ts = datetime(2023, 5, 1, tzinfo=UTC).timestamp()
    config = _make_config_mock(last_boost_timestamp=None, legacy_records={str(member.id): old_ts})
    cog = _make_cog(bot, config)

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=_outcome("settled"))
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    unicornia.apply_operation.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_boost_reward_skips_when_premium_since_none() -> None:
    """If premium_since is None (boost revoked by the time we check), do nothing."""
    bot = MagicMock()
    cog = _make_cog(bot)

    member = _make_member(premium_since=None)

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=_outcome("settled"))
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    unicornia.apply_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_boost_reward_logs_warning_when_unicornia_missing() -> None:
    """If Unicornia cog is absent, no exception is raised and nothing is awarded."""
    bot = MagicMock()
    bot.get_cog.return_value = None  # Unicornia not loaded
    config = _make_config_mock(last_boost_timestamp=None)
    cog = _make_cog(bot, config)

    ts = datetime(2024, 3, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)

    # Should complete without raising
    await cog.process_boost_reward(member)

    config.member(member).last_boost_timestamp.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_boost_reward_handles_not_ready_unicornia() -> None:
    """If Unicornia is not ready (None outcome), the timestamp is NOT persisted."""
    bot = MagicMock()
    config = _make_config_mock(last_boost_timestamp=None)
    cog = _make_cog(bot, config)

    ts = datetime(2024, 6, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=None)
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    config.member(member).last_boost_timestamp.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_boost_reward_handles_unexpected_state() -> None:
    """An unexpected operation state does not mark completion."""
    bot = MagicMock()
    config = _make_config_mock(last_boost_timestamp=None)
    cog = _make_cog(bot, config)

    ts = datetime(2024, 6, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=_outcome("insufficient_funds"))
    bot.get_cog.return_value = unicornia

    await cog.process_boost_reward(member)

    config.member(member).last_boost_timestamp.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_boost_reward_handles_exception_from_unicornia() -> None:
    """Exceptions raised by apply_operation are caught and do not propagate."""
    bot = MagicMock()
    cog = _make_cog(bot)

    ts = datetime(2024, 9, 1, tzinfo=UTC)
    member = _make_member(premium_since=ts)

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(side_effect=RuntimeError("DB error"))
    bot.get_cog.return_value = unicornia

    # Must not raise
    await cog.process_boost_reward(member)


# ---------------------------------------------------------------------------
# Unit tests — on_member_update guard logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_member_update_ignores_non_boost_changes() -> None:
    """on_member_update does nothing when premium_since didn't change from None."""
    cog = _make_cog()
    cog.process_boost_reward = AsyncMock()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    before = _make_member(premium_since=ts)  # was already boosting
    after = _make_member(premium_since=ts)  # still boosting — no change

    await cog.on_member_update(before, after)

    cog.process_boost_reward.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_member_update_ignores_boost_end() -> None:
    """on_member_update does nothing when a boost is removed (after.premium_since is None)."""
    cog = _make_cog()
    cog.process_boost_reward = AsyncMock()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    before = _make_member(premium_since=ts)
    after = _make_member(premium_since=None)  # boost ended

    await cog.on_member_update(before, after)

    cog.process_boost_reward.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_member_update_triggers_reward_on_new_boost() -> None:
    """on_member_update calls process_boost_reward when before=None, after=boosting."""
    cog = _make_cog()
    cog.process_boost_reward = AsyncMock()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    before = _make_member(premium_since=None)
    after = _make_member(premium_since=ts)

    await cog.on_member_update(before, after)

    cog.process_boost_reward.assert_awaited_once_with(after)


@pytest.mark.asyncio
async def test_on_member_update_prevents_concurrent_processing() -> None:
    """A second concurrent on_member_update for the same guild/member is dropped."""
    cog = _make_cog()
    cog.process_boost_reward = AsyncMock()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    before = _make_member(user_id=42, premium_since=None)
    after = _make_member(user_id=42, premium_since=ts)

    # Simulate the guild/member pair already being processed
    cog.processing_members.add((GUILD_ID, after.id))

    await cog.on_member_update(before, after)

    cog.process_boost_reward.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_member_update_same_user_other_guild_not_suppressed() -> None:
    """Processing in one guild does not suppress the same user's boost in another."""
    cog = _make_cog()
    cog.process_boost_reward = AsyncMock()

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    before = _make_member(user_id=42, premium_since=None, guild_id=999)
    after = _make_member(user_id=42, premium_since=ts, guild_id=999)

    # The same user is mid-processing in a *different* guild
    cog.processing_members.add((GUILD_ID, after.id))

    await cog.on_member_update(before, after)

    cog.process_boost_reward.assert_awaited_once_with(after)


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
    before.guild = guild

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    after = MagicMock(spec=discord.Member)
    after.premium_since = ts
    after.id = member.id
    after.guild = guild

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
    guild = dpytest.get_config().guilds[0]

    before = MagicMock(spec=discord.Member)
    before.premium_since = ts
    before.id = 99
    before.guild = guild

    after = MagicMock(spec=discord.Member)
    after.premium_since = ts  # unchanged — no new boost
    after.id = 99
    after.guild = guild

    bot.dispatch("member_update", before, after)
    await dpytest.run_all_events()

    pending = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    cog.process_boost_reward.assert_not_awaited()
