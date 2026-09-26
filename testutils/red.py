"""Real Red running on SimCord's in-memory Discord.

``simcord_bot`` builds an actual ``Red`` (core cogs, global checks, JSON Config in
``tmp_path``) and ``red_env`` (SimCord's ``simcord_env`` plus a clock fix) logs it in
and brings it to READY. Cogs load the way production loads them: set ``red_cogs``
in a test module.

    @pytest.fixture
    def red_cogs() -> list[str]:
        return ["tickets"]
"""

import asyncio
import gc
import sys
import weakref
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import discord
import pytest
import pytest_asyncio
import simcord
from redbot.core import _drivers, data_manager, version_info
from redbot.core import config as red_config
from redbot.core._cli import parse_cli_flags
from redbot.core._drivers import json as json_driver
from redbot.core.bot import Red
from redbot.core.core_commands import Core

REPO_ROOT = Path(__file__).resolve().parent.parent
PREFIX = "!"


@pytest.fixture
def red_cogs() -> list[str]:
    """Cog packages from this repo to load at startup; override per test module."""
    return []


@pytest_asyncio.fixture
async def simcord_bot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, red_cogs: list[str]) -> AsyncIterator[Red]:
    # Red keeps storage state in module globals: point it at tmp_path and start empty.
    # Collect first so drivers left by earlier tests finalize against the old globals.
    gc.collect()
    monkeypatch.setattr(
        data_manager,
        "basic_config",
        {**data_manager.basic_config_default, "DATA_PATH": str(tmp_path), "STORAGE_TYPE": "JSON"},
    )
    monkeypatch.setattr(data_manager, "_instance_name", "simcord")
    monkeypatch.setattr(red_config, "_config_cache", weakref.WeakValueDictionary())
    monkeypatch.setattr(json_driver, "_shared_datastore", {})
    monkeypatch.setattr(json_driver, "_driver_counts", {})
    monkeypatch.setattr(json_driver, "_finalizers", [])
    # Locks bind to the event loop that first used them, and each test gets a new loop.
    monkeypatch.setattr(json_driver, "_locks", defaultdict(asyncio.Lock))
    # `[p]slash sync` has a 60 s global cooldown, and every bot's copy of the command shares one
    # Cooldown object, so one test's sync would block the next test's with "recently syncing".
    sync_cooldown = Core.slash_sync._buckets._cooldown
    assert sync_cooldown is not None
    sync_cooldown.reset()
    # on_ready checks PyPI for a newer Red; tests stay offline.
    # By dotted path: importing redbot.core._events before redbot.core.bot is a circular import.
    monkeypatch.setattr(
        "redbot.core._events.fetch_latest_red_version_info", AsyncMock(return_value=(version_info, None))
    )

    # redbot.__main__.run_bot does these before constructing Red.
    await _drivers.get_driver_class().initialize(**data_manager.storage_details())
    (data_manager.cog_data_path(raw_name="Downloader") / "lib").mkdir(parents=True)

    flags = ["simcord", "--no-prompt", "--prefix", PREFIX]
    if red_cogs:
        flags += ["--cog-path", str(REPO_ROOT), "--load-cogs", *red_cogs]
    # Red is an AutoShardedBot; SimCord needs the shard count up front.
    bot = Red(cli_flags=parse_cli_flags(flags), description="Red", dm_help=None, shard_count=1)
    # Red.start() runs this before login(); SimCord only calls login(), which runs setup_hook.
    await bot._pre_login()
    # A fresh instance looks like a Python upgrade to Red, which then skips --load-cogs.
    async with bot._config.last_system_info() as system_info:
        system_info["python_version"] = list(sys.version_info[:2])

    yield bot

    # SimCord already detached the bot; unloading runs each cog's cog_unload. Unloading also
    # drops the package from sys.modules, so put it back for tests that imported it directly.
    modules = dict(sys.modules)
    for name in list(bot.extensions):
        await bot.unload_extension(name)
    sys.modules.update(modules)
    # A driver's GC finalizer deletes its cog's shared data; stop this test's drivers
    # from later wiping the next test's data.
    for finalizer in json_driver._finalizers:
        finalizer.detach()


@pytest_asyncio.fixture
async def red_env(simcord_env: simcord.Env, monkeypatch: pytest.MonkeyPatch) -> simcord.Env:
    # ponytail: SimCord 2.2.1 stamps snowflakes from a virtual clock starting 2026-01-01 but
    # leaves discord.utils.utcnow on the wall clock, so every interaction looks >15 min old and
    # hybrid ctx.send skips the interaction response. Uses SimCord's internal backend; drop this
    # once SimCord virtualizes utcnow itself.
    monkeypatch.setattr(discord.utils, "utcnow", lambda: datetime.fromisoformat(simcord_env.backend.now_iso()))
    return simcord_env
