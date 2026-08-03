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


@pytest.mark.asyncio
async def test_member_join_bot_add(
    bot: dpy_commands.Bot,
    config_mock: MagicMock,
) -> None:
    """on_member_join fires for a bot member and calls get_bot_add_culprit."""
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "antinuke.antinuke.Config.get_conf",
            lambda *a, **kw: config_mock,
        )
        cog = AntiNuke(bot)  # type: ignore[arg-type]

    cog.config = config_mock
    cog.event_handlers.config = config_mock
    cog.event_handlers.audit_helper.config = config_mock
    cog.event_handlers.quarantine_actions.config = config_mock

    cog.event_handlers.audit_helper.get_bot_add_culprit = AsyncMock(return_value=None)
    cog.event_handlers.quarantine_actions.execute_quarantine = AsyncMock()

    await bot.add_cog(cog)

    guild = dpytest.get_config().guilds[0]

    # Create the user and mark as bot BEFORE joining so the cog sees member.bot == True.
    bot_user = dpytest.back.make_user("TestBot", "9999")
    bot_user.bot = True  # type: ignore[misc]
    await dpytest.member_join(guild=guild, user=bot_user)

    # Drain all dispatched _run_event tasks (replaces fragile asyncio.sleep)
    await dpytest.run_all_events()

    # Drain any remaining tasks created inside event handlers (e.g. create_task)
    pending = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    cog.event_handlers.audit_helper.get_bot_add_culprit.assert_called_once_with(guild, bot_user.id, 60)


@pytest.mark.asyncio
async def test_guild_channel_delete_via_event(
    bot: dpy_commands.Bot,
    config_mock: MagicMock,
) -> None:
    """on_guild_channel_delete dispatched through the cog triggers investigation at threshold."""
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "antinuke.antinuke.Config.get_conf",
            lambda *a, **kw: config_mock,
        )
        cog = AntiNuke(bot)  # type: ignore[arg-type]

    cog.config = config_mock
    cog.event_handlers.config = config_mock
    cog.event_handlers.audit_helper.config = config_mock
    cog.event_handlers.quarantine_actions.config = config_mock

    investigate_mock = AsyncMock()
    cog.event_handlers._investigate_channel_deletion = investigate_mock

    await bot.add_cog(cog)

    channel = dpytest.get_config().channels[0]

    # Helper: dispatch an event then drain all pending _run_event coroutines.
    async def _dispatch(event: str, *args: object) -> None:
        bot.dispatch(event, *args)
        await dpytest.run_all_events()

    # Dispatch twice — threshold is 2, so investigation fires on the second call.
    await _dispatch("guild_channel_delete", channel)
    await _dispatch("guild_channel_delete", channel)

    # Drain any create_task coroutines spawned inside the event handlers.
    pending = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    # _investigate_channel_deletion should be scheduled exactly once at threshold.
    investigate_mock.assert_called_once()
