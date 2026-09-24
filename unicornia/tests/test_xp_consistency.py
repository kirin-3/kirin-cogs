"""XP accounting regressions using the real level formula and temporary SQLite."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncGenerator, Coroutine
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import commands

from unicornia.commands.level import LevelCommands
from unicornia.database import DatabaseManager
from unicornia.systems.xp_system import XPSystem
from unicornia.unicornia import Unicornia

USER = 101
GUILD = 202
CHANNEL = 303


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "xp.db"))
    await manager.connect()
    await manager.initialize()
    try:
        yield manager
    finally:
        await manager.close()


@pytest_asyncio.fixture
async def xp(db: DatabaseManager) -> AsyncGenerator[XPSystem, None]:
    config = MagicMock()
    config.xp_enabled = AsyncMock(return_value=True)
    config.xp_cooldown = AsyncMock(return_value=0)
    config.xp_per_message = AsyncMock(return_value=1)
    config.guild.return_value.xp_included_channels = AsyncMock(return_value=[CHANNEL])
    config.guild.return_value.xp_double_channels = AsyncMock(return_value=[])
    config.guild.return_value.excluded_roles = AsyncMock(return_value=[])
    bot = MagicMock()
    bot.get_context = AsyncMock(return_value=MagicMock(valid=False))
    bot.wait_until_ready = AsyncMock()
    with patch.object(XPSystem, "start_loops"), patch("unicornia.systems.xp_system.XPCardGenerator"):
        system = XPSystem(db, config, bot)
    await asyncio.gather(*system._background_tasks)
    with patch.object(system, "_handle_level_up", new=AsyncMock()):
        yield system
    await asyncio.gather(*system._background_tasks)


def message(*, user: int = USER, guild: int = GUILD) -> MagicMock:
    result = MagicMock(spec=discord.Message)
    result.author = MagicMock(spec=discord.Member, id=user, bot=False, roles=[])
    result.guild = MagicMock(spec=discord.Guild, id=guild)
    result.channel = MagicMock(spec=discord.TextChannel, id=CHANNEL)
    result.channel.send = AsyncMock()
    return result


async def direct_award(xp: XPSystem, source: str, amount: int) -> None:
    if source == "owner":
        assert await xp.award_xp(USER, GUILD, amount)
    else:
        await xp._award_voice_xp([(USER, GUILD, amount)])


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["owner", "voice"])
async def test_direct_award_cannot_announce_level_four_at_level_nineteen(xp: XPSystem, source: str) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 196)
    await xp.process_message(message())
    await xp._flush_buffer()
    await direct_award(xp, source, 2026)
    await xp.process_message(message())

    # Check the notification before the reader has a chance to refresh the cache.
    assert isinstance(xp._handle_level_up, AsyncMock)
    xp._handle_level_up.assert_not_awaited()
    stats = await xp.get_user_level_stats(USER, GUILD)
    assert (stats.total_xp, stats.level) == (2224, 19)
    await xp._flush_buffer()
    assert await xp.db.xp.get_user_xp(USER, GUILD) == 2224


@pytest.mark.asyncio
async def test_level_read_includes_unflushed_message(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    msg = message()
    await xp.process_message(msg)
    assert isinstance(xp._handle_level_up, AsyncMock)
    xp._handle_level_up.assert_awaited_once_with(msg, 3, 4)
    stats = await xp.get_user_level_stats(USER, GUILD)
    assert (stats.total_xp, stats.level, stats.level_xp) == (198, 4, 0)
    assert await xp.db.xp.get_user_xp(USER, GUILD) == 197


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["owner", "voice"])
async def test_direct_award_preserves_pending_xp_and_other_guild(xp: XPSystem, source: str) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 100)
    await xp.db.xp.add_xp(USER, GUILD + 1, 50)
    await xp.get_user_level_stats(USER, GUILD + 1)
    for _ in range(3):
        await xp.process_message(message())
    await direct_award(xp, source, 10)
    assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 113
    assert (await xp.get_user_level_stats(USER, GUILD + 1)).total_xp == 50
    await xp._flush_buffer()
    assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 113


@pytest.mark.asyncio
async def test_lru_eviction_preserves_pending_xp(xp: XPSystem) -> None:
    xp.user_xp_cache_size = 1
    await xp.db.xp.add_xp(USER, GUILD, 100)
    for _ in range(3):
        await xp.process_message(message())
    await xp.process_message(message(user=USER + 1))
    assert (USER, GUILD) not in xp.user_xp_cache
    await xp.process_message(message())
    assert xp.xp_buffer[(USER, GUILD)] == 4
    assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 104


async def global_xp(db: DatabaseManager) -> int:
    async with db._get_connection() as connection:
        row = await (await connection.execute("SELECT TotalXp FROM DiscordUser WHERE UserId = ?", (USER,))).fetchone()
    assert row is not None
    return row[0]


async def fail_global_writes(db: DatabaseManager, *, enabled: bool) -> None:
    async with db._get_connection() as connection:
        if enabled:
            await connection.execute(
                "CREATE TRIGGER fail_xp BEFORE INSERT ON DiscordUser "
                "BEGIN SELECT RAISE(ABORT, 'injected XP failure'); END"
            )
        else:
            await connection.execute("DROP TRIGGER fail_xp")
        await connection.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("bulk", [False, True])
async def test_partial_write_rolls_back_both_totals_and_can_retry(db: DatabaseManager, bulk: bool) -> None:
    await db.xp.add_xp(USER, GUILD, 100)
    await fail_global_writes(db, enabled=True)

    async def write() -> None:
        if bulk:
            await db.xp.add_xp_bulk([(USER, GUILD, 3)])
        else:
            await db.xp.add_xp(USER, GUILD, 3)

    with pytest.raises(sqlite3.IntegrityError, match="injected XP failure"):
        await write()
    assert await db.xp.get_user_xp(USER, GUILD) == 100
    assert await global_xp(db) == 100
    await fail_global_writes(db, enabled=False)
    await write()
    assert await db.xp.get_user_xp(USER, GUILD) == 103
    assert await global_xp(db) == 103


async def start_operation(coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
    """Return once the operation has started and reached its first blocking await."""
    started = asyncio.Event()

    async def run() -> Any:
        started.set()
        return await coro

    task = asyncio.create_task(run())
    await started.wait()
    return task


@pytest.mark.asyncio
async def test_read_and_second_flush_wait_for_first_flush(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    await xp.process_message(message())
    entered, release = asyncio.Event(), asyncio.Event()
    original = xp.db.xp.add_xp_bulk

    async def paused_write(updates: list[tuple[int, int, int]]) -> None:
        entered.set()
        await release.wait()
        await original(updates)

    async with asyncio.timeout(5):
        with patch.object(xp.db.xp, "add_xp_bulk", side_effect=paused_write) as write:
            first = asyncio.create_task(xp._flush_buffer())
            await entered.wait()
            read = await start_operation(xp.get_user_level_stats(USER, GUILD))
            second = await start_operation(xp._flush_buffer())
            assert not read.done() and not second.done()
            release.set()
            await asyncio.gather(first, second)
            stats = await read
            assert (stats.total_xp, stats.level) == (198, 4)
            write.assert_awaited_once()
    assert not xp.xp_buffer
    assert await xp.db.xp.get_user_xp(USER, GUILD) == await global_xp(xp.db) == 198


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["owner", "voice"])
async def test_message_waits_for_direct_award_and_rebuilds_cache(xp: XPSystem, source: str) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 100)
    await xp.get_user_level_stats(USER, GUILD)
    entered, release = asyncio.Event(), asyncio.Event()
    original = xp.db.xp.add_xp_bulk

    async def paused_write(updates: list[tuple[int, int, int]]) -> None:
        entered.set()
        await release.wait()
        await original(updates)

    async with asyncio.timeout(5):
        with patch.object(xp.db.xp, "add_xp_bulk", side_effect=paused_write):
            award = asyncio.create_task(direct_award(xp, source, 2))
            await entered.wait()
            chat = await start_operation(xp.process_message(message()))
            assert not chat.done()
            release.set()
            await asyncio.gather(award, chat)
    assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 103
    await xp._flush_buffer()
    assert await xp.db.xp.get_user_xp(USER, GUILD) == await global_xp(xp.db) == 103


@pytest.mark.asyncio
async def test_simultaneous_messages_admit_one_gain_per_cooldown(xp: XPSystem) -> None:
    xp._config_cache["xp_cooldown"] = 60
    entered, release = asyncio.Event(), asyncio.Event()
    original = xp.db.xp.get_user_xp

    async def paused_read(uid: int, gid: int) -> int:
        entered.set()
        await release.wait()
        return await original(uid, gid)

    async with asyncio.timeout(5):
        with patch.object(xp.db.xp, "get_user_xp", side_effect=paused_read):
            first = asyncio.create_task(xp.process_message(message()))
            await entered.wait()
            second = await start_operation(xp.process_message(message()))
            release.set()
            await asyncio.gather(first, second)
    assert xp.xp_buffer[(USER, GUILD)] == 1
    assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 1


@pytest.mark.asyncio
async def test_failed_flush_retains_effective_xp_and_retries_once(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 100)
    for _ in range(3):
        await xp.process_message(message())
    await fail_global_writes(xp.db, enabled=True)
    await xp._flush_buffer()
    assert await xp.db.xp.get_user_xp(USER, GUILD) == await global_xp(xp.db) == 100
    assert xp.xp_buffer[(USER, GUILD)] == 3
    assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 103
    await fail_global_writes(xp.db, enabled=False)
    await xp._flush_buffer()
    await xp._flush_buffer()
    assert not xp.xp_buffer
    assert await xp.db.xp.get_user_xp(USER, GUILD) == await global_xp(xp.db) == 103


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["owner", "voice"])
async def test_failed_direct_award_leaves_cache_and_pending_xp_intact(xp: XPSystem, source: str) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 100)
    await xp.process_message(message())
    before = xp.user_xp_cache[(USER, GUILD)].copy()
    await fail_global_writes(xp.db, enabled=True)
    if source == "owner":
        assert not await xp.award_xp(USER, GUILD, 10)
    else:
        with pytest.raises(sqlite3.IntegrityError):
            await xp._award_voice_xp([(USER, GUILD, 10)])
    assert xp.user_xp_cache[(USER, GUILD)] == before
    assert xp.xp_buffer[(USER, GUILD)] == 1
    assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 101
    assert await xp.db.xp.get_user_xp(USER, GUILD) == await global_xp(xp.db) == 100


async def write_operation(xp: XPSystem, source: str) -> None:
    if source == "flush":
        await xp._flush_buffer()
    else:
        await direct_award(xp, source, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["flush", "owner", "voice"])
@pytest.mark.parametrize("phase", ["before_commit", "after_commit", "failure"])
async def test_cancellation_resolves_write_before_unlocking(xp: XPSystem, source: str, phase: str) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 100)
    await xp.process_message(message())
    entered, release = asyncio.Event(), asyncio.Event()
    original = xp.db.xp.add_xp_bulk

    async def paused_write(updates: list[tuple[int, int, int]]) -> None:
        if phase == "after_commit":
            await original(updates)
        entered.set()
        await release.wait()
        if phase == "failure":
            raise sqlite3.OperationalError("injected failure before commit")
        if phase == "before_commit":
            await original(updates)

    async with asyncio.timeout(5):
        with patch.object(xp.db.xp, "add_xp_bulk", side_effect=paused_write):
            operation = asyncio.create_task(write_operation(xp, source))
            await entered.wait()
            operation.cancel()
            reader = await start_operation(xp.get_user_level_stats(USER, GUILD))
            assert not operation.done() and not reader.done()
            assert xp._state_lock.locked()
            assert xp._background_tasks
            operation.cancel()  # Repeated cancellation must not detach the write.
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await operation
            stats = await reader
    expected = 101 if source == "flush" or phase == "failure" else 103
    assert stats.total_xp == expected
    assert not xp._state_lock.locked() and not xp._background_tasks
    assert xp.xp_buffer.get((USER, GUILD), 0) == (0 if source == "flush" and phase != "failure" else 1)
    await xp._flush_buffer()
    assert await xp.db.xp.get_user_xp(USER, GUILD) == await global_xp(xp.db) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["flush", "owner", "voice"])
async def test_cancel_while_waiting_for_lock_does_not_start_write(xp: XPSystem, source: str) -> None:
    await xp.process_message(message())
    async with asyncio.timeout(5):
        async with xp._state_lock:
            operation = await start_operation(write_operation(xp, source))
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
            assert not xp._background_tasks
    assert xp.xp_buffer[(USER, GUILD)] == 1
    assert await xp.db.xp.get_user_xp(USER, GUILD) == 0
    await xp._flush_buffer()
    assert await xp.db.xp.get_user_xp(USER, GUILD) == 1


@pytest.mark.asyncio
async def test_cumulative_threshold_and_real_notification(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 196)
    stats = await xp.get_user_level_stats(USER, GUILD)
    assert stats.required_xp == 63
    assert xp.user_xp_cache[(USER, GUILD)]["next_level_total_xp"] == 198
    msg = message()
    with patch.object(xp.db, "calculate_level_stats", wraps=xp.db.calculate_level_stats) as calculate:
        await xp.process_message(msg)
        calculate.assert_not_called()  # Cached cumulative boundary has not been reached.
    assert isinstance(xp._handle_level_up, AsyncMock)
    xp._handle_level_up.assert_not_awaited()

    async def notify(*args: Any) -> None:
        await XPSystem._handle_level_up(xp, *args)

    with patch.object(xp, "_handle_level_up", side_effect=notify) as notify_mock:
        await xp.process_message(msg)
        await xp.process_message(msg)
        notify_mock.assert_awaited_once_with(msg, 3, 4)
    sent = msg.channel.send.await_args.kwargs["embed"]
    assert "level **4**" in sent.description
    assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 199


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["notification", "reward"])
async def test_failed_side_effect_keeps_xp_and_does_not_replay(xp: XPSystem, stage: str) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    msg = message()
    callback = msg.channel.send if stage == "notification" else AsyncMock()
    callback.side_effect = RuntimeError("injected Discord failure")
    await xp.db.xp.add_xp_currency_reward(GUILD, 4, 20)

    async def notify(*args: Any) -> None:
        if stage == "reward":
            await callback()
        else:
            await XPSystem._handle_level_up(xp, *args)

    with patch.object(xp, "_handle_level_up", side_effect=notify) as notify_mock:
        await xp.process_message(msg)
        assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 198
        assert USER in xp.xp_cooldowns
        await xp.process_message(msg)
        notify_mock.assert_awaited_once_with(msg, 3, 4)
    if stage == "notification":
        # Even when the send fails after currency delivery, the reward is not replayed.
        assert await xp.db.economy.get_user_currency(USER) == 20
    await xp._flush_buffer()
    assert await xp.db.xp.get_user_xp(USER, GUILD) == 199


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["notification", "reward"])
async def test_slow_side_effect_does_not_hold_state_lock(xp: XPSystem, stage: str) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    msg = message()
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await release.wait()
        return []

    async def notify(*args: Any) -> None:
        await XPSystem._handle_level_up(xp, *args)

    target = msg.channel if stage == "notification" else xp.db.xp
    method = "send" if stage == "notification" else "get_all_xp_role_rewards"
    async with asyncio.timeout(5):
        with patch.object(xp, "_handle_level_up", side_effect=notify), patch.object(target, method, side_effect=pause):
            chat = asyncio.create_task(xp.process_message(msg))
            await entered.wait()
            assert not xp._state_lock.locked()
            assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 198
            await xp._flush_buffer()
            assert await xp.db.xp.get_user_xp(USER, GUILD) == 198
            release.set()
            await chat


@pytest.mark.asyncio
async def test_voice_loop_invalidates_cached_message_level(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    await xp.get_user_level_stats(USER, GUILD)
    msg = message()
    msg.author.voice = MagicMock(self_deaf=False, deaf=False)
    voice = MagicMock(id=CHANNEL, members=[msg.author])
    msg.guild.voice_channels = [voice]
    xp.bot.guilds = [msg.guild]
    with patch(
        "unicornia.systems.xp_system.asyncio.sleep", new=AsyncMock(side_effect=[None, asyncio.CancelledError()])
    ):
        await xp._voice_xp_loop()
    assert (USER, GUILD) not in xp.user_xp_cache
    assert await xp.db.xp.get_user_xp(USER, GUILD) == 198
    await xp.process_message(msg)
    assert isinstance(xp._handle_level_up, AsyncMock)
    xp._handle_level_up.assert_not_awaited()
    assert (await xp.get_user_level_stats(USER, GUILD)).total_xp == 199


class LevelTestCog(LevelCommands, commands.Cog):
    """Exercise the actual Red level commands without unrelated Unicornia systems."""

    def __init__(self, xp: XPSystem) -> None:
        self.config = xp.config
        self.db = xp.db
        self.xp_system = xp


@pytest_asyncio.fixture
async def command_bot(
    xp: XPSystem, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[dpy_commands.Bot, None]:
    # dpytest stages uploaded attachments in the current directory.
    monkeypatch.chdir(tmp_path)
    intents = discord.Intents.default()
    intents.members = intents.message_content = True
    bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(bot)
    await bot.add_cog(LevelTestCog(xp))
    try:
        # dpytest supplies a discord.py bot, not Red's permission service.
        # Keep parsing and callbacks real; permission behavior is outside this test.
        with patch.object(commands.Command, "can_run", new=AsyncMock(return_value=True)):
            yield bot
    finally:
        await dpytest.empty_queue()
        await bot.remove_cog("LevelTestCog")
        # dpytest's fake websocket has no live socket to close.
        with patch.object(bot, "ws", None):
            await bot.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["xp", "level", "level check"])
@pytest.mark.parametrize("image_mode", ["card", "empty", "error"])
async def test_level_commands_use_effective_snapshot(
    xp: XPSystem, command_bot: dpy_commands.Bot, command: str, image_mode: str
) -> None:
    # Use dpytest's member/channel IDs while earning XP through the real message path.
    channel = dpytest.get_config().channels[0]
    member = dpytest.get_config().members[0]
    await xp.db.xp.add_xp(member.id, channel.guild.id, 197)
    msg = message(user=member.id, guild=channel.guild.id)
    await xp.process_message(msg)
    if image_mode == "error":
        generator = AsyncMock(side_effect=RuntimeError("image unavailable"))
    else:
        generator = AsyncMock(return_value=(BytesIO(b"rendered card") if image_mode == "card" else None, "png"))
    with patch.object(xp.card_generator, "generate_xp_card", generator):
        await dpytest.message(f"!{command}")
        await dpytest.run_all_events()
        response = dpytest.get_message()
    assert generator.await_args is not None
    args = generator.await_args.args
    assert (args[3], args[4], args[5], args[6]) == (4, 0, 72, 198)
    if image_mode == "card":
        assert response.attachments[0].filename == "xp_card.png"
        assert not response.embeds
    else:
        fields = {field.name: field.value for field in response.embeds[0].fields}
        assert fields["Level"] == "4"
        assert fields["Total XP"] == "198"
        assert fields["XP"] == "0/72"
    assert await xp.db.xp.get_user_xp(member.id, channel.guild.id) == 197


@pytest.mark.asyncio
async def test_shutdown_waits_for_active_flush_and_stops_admission(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 100)
    await xp.process_message(message())
    entered, release = asyncio.Event(), asyncio.Event()
    original = xp.db.xp.add_xp_bulk

    async def paused_write(updates: list[tuple[int, int, int]]) -> None:
        entered.set()
        await release.wait()
        await original(updates)

    async with asyncio.timeout(5):
        with patch.object(xp.db.xp, "add_xp_bulk", side_effect=paused_write):
            # Simulate the periodic message loop already flushing when unload starts.
            xp._message_xp_task = asyncio.create_task(xp._flush_buffer())
            loop = xp._message_xp_task
            await entered.wait()
            stop = await start_operation(xp.stop_loops())
            assert xp._stopping and not stop.done()
            await xp.process_message(message())
            voice = await start_operation(xp._award_voice_xp([(USER, GUILD, 10)]))
            owner = await start_operation(xp.award_xp(USER, GUILD, 10))
            release.set()
            await asyncio.gather(stop, voice)
            assert not await owner
    assert loop.done()
    assert not xp.xp_buffer and not xp._background_tasks
    assert await xp.db.xp.get_user_xp(USER, GUILD) == await global_xp(xp.db) == 101
    xp.start_loops()
    assert xp._message_xp_task is None and xp._voice_xp_task is None


@pytest.mark.asyncio
async def test_shutdown_drains_level_up_callback_before_final_flush(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    entered, release = asyncio.Event(), asyncio.Event()

    async def callback(*args: Any) -> None:
        entered.set()
        await release.wait()
        assert await xp.db.xp.get_user_xp(USER, GUILD) == 197

    async with asyncio.timeout(5):
        with patch.object(xp, "_handle_level_up", side_effect=callback):
            chat = asyncio.create_task(xp.process_message(message()))
            await entered.wait()
            stop = await start_operation(xp.stop_loops())
            assert not stop.done()
            release.set()
            await asyncio.gather(chat, stop)
    assert not xp._background_tasks and not xp.xp_buffer
    assert await xp.db.xp.get_user_xp(USER, GUILD) == 198


@pytest.mark.asyncio
async def test_cog_unload_stops_xp_before_database_close_and_replacement_preserves_xp(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    await xp.process_message(message())
    xp.start_loops()
    loops = (xp._voice_xp_task, xp._message_xp_task)
    with patch("unicornia.unicornia.Config.get_conf", return_value=xp.config):
        cog = Unicornia(xp.bot)
    cog.xp_system = xp
    cog.db = xp.db
    original_close = xp.db.close

    async def close_after_drain() -> None:
        assert xp._stopping and not xp.xp_buffer and not xp._background_tasks
        assert all(task is not None and task.done() for task in loops)
        await original_close()

    with patch.object(xp.db, "close", side_effect=close_after_drain) as close:
        await cog.cog_unload()
        close.assert_awaited_once()
    with patch.object(XPSystem, "start_loops"), patch("unicornia.systems.xp_system.XPCardGenerator"):
        replacement = XPSystem(xp.db, xp.config, xp.bot)
    await asyncio.gather(*replacement._background_tasks)
    try:
        assert not replacement.user_xp_cache
        stats = await replacement.get_user_level_stats(USER, GUILD)
        assert (stats.total_xp, stats.level) == (198, 4)
        await xp.process_message(message())
        assert not await xp.award_xp(USER, GUILD, 10)
        await replacement.process_message(message())
        assert (await replacement.get_user_level_stats(USER, GUILD)).total_xp == 199
    finally:
        await replacement.stop_loops()


@pytest.mark.asyncio
async def test_failed_shutdown_flush_is_logged_and_keeps_pending_xp(
    xp: XPSystem, caplog: pytest.LogCaptureFixture
) -> None:
    await xp.process_message(message())
    await fail_global_writes(xp.db, enabled=True)
    await xp.stop_loops()
    assert "XP shutdown could not persist 1 pending entries" in caplog.text
    assert xp.xp_buffer[(USER, GUILD)] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, {}, "invalid", [None, {}, True]])
async def test_malformed_channel_configuration_does_not_award_xp(xp: XPSystem, raw: Any) -> None:
    xp.config.guild.return_value.xp_included_channels.return_value = raw
    await xp.process_message(message())
    assert not xp.xp_buffer


@pytest.mark.asyncio
async def test_config_cache_handles_missing_values_and_preserves_zero_rate(xp: XPSystem) -> None:
    xp.config.xp_enabled.return_value = None
    xp.config.xp_cooldown.return_value = {}
    xp.config.xp_per_message.return_value = None
    await xp._init_config_cache()
    assert xp._config_cache == {"xp_enabled": True, "xp_cooldown": 60, "xp_per_message": 1}
    xp.config.xp_per_message.return_value = 0
    await xp._init_config_cache()
    await xp.process_message(message())
    assert not xp.xp_buffer


@pytest.mark.asyncio
async def test_shutdown_rejects_message_still_loading_initial_xp(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    entered, release = asyncio.Event(), asyncio.Event()
    original = xp.db.xp.get_user_xp

    async def paused_read(uid: int, gid: int) -> int:
        entered.set()
        await release.wait()
        return await original(uid, gid)

    async with asyncio.timeout(5):
        with patch.object(xp.db.xp, "get_user_xp", side_effect=paused_read):
            chat = asyncio.create_task(xp.process_message(message()))
            await entered.wait()
            stop = await start_operation(xp.stop_loops())
            assert xp._stopping
            release.set()
            await asyncio.gather(chat, stop)
    assert not xp.xp_buffer and not xp._background_tasks
    assert isinstance(xp._handle_level_up, AsyncMock)
    xp._handle_level_up.assert_not_awaited()
    assert await xp.db.xp.get_user_xp(USER, GUILD) == 197


@pytest.mark.asyncio
async def test_cancelling_shutdown_does_not_cancel_committed_award_bookkeeping(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 100)
    await xp.process_message(message())
    committed, release = asyncio.Event(), asyncio.Event()
    original = xp.db.xp.add_xp_bulk

    async def pause_after_commit(updates: list[tuple[int, int, int]]) -> None:
        await original(updates)
        committed.set()
        await release.wait()

    async with asyncio.timeout(5):
        with patch.object(xp.db.xp, "add_xp_bulk", side_effect=pause_after_commit):
            award = asyncio.create_task(xp.award_xp(USER, GUILD, 10))
            await committed.wait()
            stop = await start_operation(xp.stop_loops())
            stop.cancel()
            # Let cancellation reach the shutdown waiter before releasing the write.
            observer = await start_operation(xp.get_user_level_stats(USER, GUILD))
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await stop
            assert await award
            assert (await observer).total_xp == 111
    assert not xp.xp_buffer and not xp._background_tasks
    assert xp.user_xp_cache[(USER, GUILD)]["xp"] == 111
    assert await xp.db.xp.get_user_xp(USER, GUILD) == await global_xp(xp.db) == 111


@pytest.mark.asyncio
async def test_concurrent_shutdown_callers_do_not_cancel_level_up_callback(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    entered, release = asyncio.Event(), asyncio.Event()
    finished = False

    async def callback(*args: Any) -> None:
        nonlocal finished
        entered.set()
        await release.wait()
        finished = True

    async with asyncio.timeout(5):
        with patch.object(xp, "_handle_level_up", side_effect=callback):
            chat = asyncio.create_task(xp.process_message(message()))
            await entered.wait()
            first = await start_operation(xp.stop_loops())
            first.cancel()
            second = await start_operation(xp.stop_loops())
            first.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await first
            await asyncio.gather(second, chat)
    assert finished and xp._shutdown_task is not None and xp._shutdown_task.done()
    assert not xp.xp_buffer and not xp._background_tasks
    assert await xp.db.xp.get_user_xp(USER, GUILD) == 198


@pytest.mark.asyncio
async def test_xp_shutdown_is_not_skipped_when_other_cleanup_fails(xp: XPSystem) -> None:
    await xp.process_message(message())
    xp.start_loops()
    loops = (xp._voice_xp_task, xp._message_xp_task)
    with patch("unicornia.unicornia.Config.get_conf", return_value=xp.config):
        cog = Unicornia(xp.bot)
    cog.xp_system = xp
    cog.db = xp.db
    cog.currency_decay = MagicMock()
    cog.currency_decay.stop_decay_loop = AsyncMock(side_effect=RuntimeError("other cleanup failed"))
    try:
        await cog.cog_unload()
        assert xp._stopping
        assert all(task is not None and task.done() for task in loops)
        assert not xp.xp_buffer
        assert await xp.db.xp.get_user_xp(USER, GUILD) == 1
    finally:
        await xp.stop_loops()


# ---------------------------------------------------------------------------
# Rewards for every level passed, including levels jumped by admin awards and voice XP
# ---------------------------------------------------------------------------

ROLE_A, ROLE_B, ROLE_C = 1, 2, 3


def reward_guild(xp: XPSystem, *, held: tuple[int, ...] = ()) -> tuple[MagicMock, dict[int, MagicMock]]:
    """Make bot.get_guild return a guild whose member USER holds the given roles."""
    roles = {role_id: MagicMock(spec=discord.Role, id=role_id) for role_id in (ROLE_A, ROLE_B, ROLE_C)}
    for role_id, role in roles.items():
        role.name = f"role{role_id}"
    member = MagicMock(spec=discord.Member, id=USER, mention=f"<@{USER}>")
    member.roles = [roles[role_id] for role_id in held]
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    guild = MagicMock(spec=discord.Guild, id=GUILD)
    guild.get_member.side_effect = lambda user_id: member if user_id == USER else None
    guild.get_role.side_effect = roles.get
    xp.bot.get_guild.side_effect = lambda guild_id: guild if guild_id == GUILD else None
    xp.config.currency_name = AsyncMock(return_value="points")
    return member, roles


async def configure_rewards(xp: XPSystem) -> None:
    await xp.db.xp.add_xp_role_reward(GUILD, 4, ROLE_A)
    await xp.db.xp.add_xp_role_reward(GUILD, 10, ROLE_A, remove=True)
    await xp.db.xp.add_xp_role_reward(GUILD, 15, ROLE_B)
    await xp.db.xp.add_xp_role_reward(GUILD, 25, ROLE_C)
    await xp.db.xp.add_xp_currency_reward(GUILD, 4, 20)
    await xp.db.xp.add_xp_currency_reward(GUILD, 19, 30)
    await xp.db.xp.add_xp_currency_reward(GUILD, 20, 99)


@pytest.mark.asyncio
async def test_owner_award_grants_the_rewards_of_every_level_it_passes(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)  # level 3
    await configure_rewards(xp)
    member, roles = reward_guild(xp)
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()

    assert await xp.award_xp(USER, GUILD, 2027, channel=channel)  # 2224 XP: level 19

    # Levels 4 and 19 pay out; role A (given at 4, removed at 10) ends up not given; role B from 15 is
    assert await xp.db.economy.get_user_currency(USER) == 50
    member.add_roles.assert_awaited_once_with(roles[ROLE_B], reason="XP level 15 role reward")
    member.remove_roles.assert_not_awaited()
    embed = channel.send.await_args.kwargs["embed"]
    assert "level **19**" in embed.description
    assert embed.footer.text == "Gained role: role2 • Gained 50 points"
    assert isinstance(xp._handle_level_up, AsyncMock)
    xp._handle_level_up.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_award_removes_a_role_held_from_an_earlier_level(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 198)  # level 4, holding role A
    await configure_rewards(xp)
    member, roles = reward_guild(xp, held=(ROLE_A,))

    assert await xp.award_xp(USER, GUILD, 700)  # 898 XP: level 11

    member.remove_roles.assert_awaited_once_with(roles[ROLE_A], reason="XP level 10 role removal")
    member.add_roles.assert_not_awaited()
    # Level 4 was already reached before the award
    assert await xp.db.economy.get_user_currency(USER) == 0


@pytest.mark.asyncio
async def test_owner_award_without_a_level_up_grants_nothing(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 100)
    await configure_rewards(xp)
    member, _ = reward_guild(xp)

    assert await xp.award_xp(USER, GUILD, 10)

    member.add_roles.assert_not_awaited()
    assert await xp.db.economy.get_user_currency(USER) == 0


@pytest.mark.asyncio
async def test_award_includes_unflushed_message_xp_when_finding_levels_passed(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 196)
    await xp.process_message(message())  # 197, still buffered
    await configure_rewards(xp)
    reward_guild(xp)

    assert await xp.award_xp(USER, GUILD, 1)  # 198: level 4

    assert await xp.db.economy.get_user_currency(USER) == 20


@pytest.mark.asyncio
async def test_voice_xp_crossing_a_level_grants_its_rewards(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    await configure_rewards(xp)
    member, roles = reward_guild(xp)

    await xp._award_voice_xp([(USER, GUILD, 1)])
    await asyncio.gather(*xp._background_tasks)

    member.add_roles.assert_awaited_once_with(roles[ROLE_A], reason="XP level 4 role reward")
    assert await xp.db.economy.get_user_currency(USER) == 20


@pytest.mark.asyncio
async def test_level_rewards_are_not_granted_twice(xp: XPSystem) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    await configure_rewards(xp)
    reward_guild(xp)

    await xp._award_voice_xp([(USER, GUILD, 1)])
    await asyncio.gather(*xp._background_tasks)
    assert await xp.award_xp(USER, GUILD, 1)
    await xp.process_message(message())

    assert await xp.db.economy.get_user_currency(USER) == 20
    assert isinstance(xp._handle_level_up, AsyncMock)
    xp._handle_level_up.assert_not_awaited()


@pytest.mark.asyncio
async def test_member_not_cached_is_logged_and_the_award_still_counts(
    xp: XPSystem, caplog: pytest.LogCaptureFixture
) -> None:
    await xp.db.xp.add_xp(USER, GUILD, 197)
    await configure_rewards(xp)
    xp.bot.get_guild.side_effect = lambda guild_id: None

    assert await xp.award_xp(USER, GUILD, 1)

    assert await xp.db.xp.get_user_xp(USER, GUILD) == 198
    assert "level rewards 4-4 were not granted" in caplog.text
