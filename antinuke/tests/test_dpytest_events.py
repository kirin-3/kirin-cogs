"""Integration tests for AntiNuke events using dpytest."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config

from antinuke.antinuke import AntiNuke


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.all_guilds = AsyncMock(return_value={})

    config_dict = {
        "enabled": True,
        "monitor": {
            "bot_add": {
                "enabled": True,
                "threshold": 1,
                "timeframe": 60,
                "kick_bot": False,
            },
            "channel_delete": {"enabled": True, "threshold": 2, "timeframe": 60},
            "guild_prune": {"enabled": True, "threshold": 0, "timeframe": 60},
        },
        "trusted_users": [],
        "trusted_roles": [],
    }

    def side_effect(*args: object, **kwargs: object) -> object:
        class GuildGroup:
            def __getattr__(self, name: str) -> AsyncMock:
                if name in config_dict:
                    return AsyncMock(return_value=config_dict[name])
                return AsyncMock(return_value=None)

        return GuildGroup()

    config.guild.side_effect = side_effect
    return config


@pytest_asyncio.fixture
async def bot() -> AsyncGenerator[dpy_commands.Bot, None]:
    """Create a discord.py Bot configured with dpytest.

    Red's constructor requires full Redbot config initialisation which is
    incompatible with a bare test environment.  We use a plain
    ``commands.Bot`` here; cog config is replaced with ``config_mock``
    after construction, so the behaviour under test is identical.
    """
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True

    real_bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    # Bind the running event loop so bot.dispatch / create_task work correctly.
    # This mirrors what discord.py does internally during bot.start().
    await real_bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(real_bot)

    yield real_bot

    await dpytest.empty_queue()


def _load_cog(bot: dpy_commands.Bot, config_mock: MagicMock) -> AntiNuke:
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "antinuke.antinuke.Config.get_conf",
            lambda *a, **kw: config_mock,
        )
        cog = AntiNuke(bot)  # type: ignore[arg-type]

    cog.config = config_mock
    cog.event_handlers.config = config_mock
    cog.event_handlers.quarantine_actions.config = config_mock
    return cog


async def _drain() -> None:
    await dpytest.run_all_events()
    pending = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _audit_entry(guild: discord.Guild, action: discord.AuditLogAction, user_id: int) -> MagicMock:
    entry = MagicMock(spec=discord.AuditLogEntry)
    entry.guild = guild
    entry.action = action
    entry.user_id = user_id
    entry.before = discord.AuditLogDiff()
    entry.after = discord.AuditLogDiff()
    entry.target = None
    return entry


@pytest.mark.asyncio
async def test_audit_log_entry_create_event_reaches_cog(
    bot: dpy_commands.Bot,
    config_mock: MagicMock,
) -> None:
    """discord.py's audit_log_entry_create event is wired to the cog and a prune is acted on."""
    cog = _load_cog(bot, config_mock)
    cog.event_handlers.quarantine_actions.execute_quarantine = AsyncMock()
    await bot.add_cog(cog)

    guild = dpytest.get_config().guilds[0]
    member = dpytest.get_config().members[0]

    bot.dispatch("audit_log_entry_create", _audit_entry(guild, discord.AuditLogAction.member_prune, member.id))
    await _drain()

    cog.event_handlers.quarantine_actions.execute_quarantine.assert_awaited_once()
    await_args = cog.event_handlers.quarantine_actions.execute_quarantine.await_args
    assert await_args is not None
    args = await_args.args
    assert args[1].id == member.id
    assert args[2] == "guild_prune"


@pytest.mark.asyncio
async def test_channel_deletes_via_event_hit_threshold(
    bot: dpy_commands.Bot,
    config_mock: MagicMock,
) -> None:
    """Two channel deletions by one member through the dispatched event quarantine that member once."""
    cog = _load_cog(bot, config_mock)
    cog.event_handlers.quarantine_actions.execute_quarantine = AsyncMock()
    await bot.add_cog(cog)

    guild = dpytest.get_config().guilds[0]
    member = dpytest.get_config().members[0]

    bot.dispatch("audit_log_entry_create", _audit_entry(guild, discord.AuditLogAction.channel_delete, member.id))
    await _drain()
    cog.event_handlers.quarantine_actions.execute_quarantine.assert_not_awaited()

    bot.dispatch("audit_log_entry_create", _audit_entry(guild, discord.AuditLogAction.channel_delete, member.id))
    await _drain()
    cog.event_handlers.quarantine_actions.execute_quarantine.assert_awaited_once()
