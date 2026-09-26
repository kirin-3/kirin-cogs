"""Settings that would remove a limit or crash spawning are refused, and bad stored values are tolerated."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from redbot.core import commands
from redbot.core.bot import Red

from testutils.migration import DictConfig
from unicornia.systems.currency_systems import CurrencyDecay, CurrencyGeneration
from unicornia.systems.economy_system import EconomySystem
from unicornia.unicornia import Unicornia

DEFAULTS: dict[str, Any] = {
    "timely_cooldown": 24,
    "xp_cooldown": 180,
    "generation_cooldown": 10,
    "generation_min_amount": 60,
    "generation_max_amount": 140,
    "decay_hour_interval": 48,
    "gambling_min_bet": 50,
    "gambling_max_bet": 1_000_000,
    "dividend_period_hours": 168,
    "decay_last_run": 0,
}


def _cog(**overrides: Any) -> tuple[Unicornia, DictConfig]:
    config = DictConfig({"global": {**DEFAULTS, **overrides}})
    with patch("unicornia.unicornia.Config.get_conf", return_value=MagicMock()):
        cog = Unicornia(MagicMock(spec=Red))
    cog.config = config  # type: ignore[assignment]
    return cog, config


async def _set(cog: Unicornia, setting: str, value: str) -> str:
    ctx = MagicMock(spec=commands.Context)
    ctx.send = AsyncMock()
    await Unicornia.config_cmd.callback(cog, ctx, setting, value=value)  # type: ignore[arg-type]
    return ctx.send.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "setting", ["timely_cooldown", "decay_hour_interval", "dividend_period_hours", "generation_min_amount"]
)
async def test_zero_is_refused_where_it_removes_the_limit(setting: str) -> None:
    cog, config = _cog()

    reply = await _set(cog, setting, "0")

    assert reply == f"❌ {setting} must be at least 1."
    assert await getattr(config, setting)() == DEFAULTS[setting]


@pytest.mark.asyncio
@pytest.mark.parametrize("setting", ["xp_cooldown", "generation_cooldown"])
async def test_zero_cooldowns_are_still_allowed(setting: str) -> None:
    cog, config = _cog()

    reply = await _set(cog, setting, "0")

    assert reply == f"✅ {setting} updated to 0"
    assert await getattr(config, setting)() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setting", "value", "reply"),
    [
        (
            "generation_min_amount",
            "200",
            "❌ generation_min_amount (200) can't be above generation_max_amount (140).",
        ),
        (
            "generation_max_amount",
            "50",
            "❌ generation_min_amount (60) can't be above generation_max_amount (50).",
        ),
        ("gambling_min_bet", "2000000", "❌ gambling_min_bet (2000000) can't be above gambling_max_bet (1000000)."),
    ],
)
async def test_minimum_above_maximum_is_refused(setting: str, value: str, reply: str) -> None:
    cog, config = _cog()

    assert await _set(cog, setting, value) == reply
    assert await getattr(config, setting)() == DEFAULTS[setting]


@pytest.mark.asyncio
async def test_minimum_equal_to_maximum_is_allowed() -> None:
    cog, config = _cog()

    assert await _set(cog, "generation_min_amount", "140") == "✅ generation_min_amount updated to 140"
    assert await config.generation_min_amount() == 140


@pytest.mark.asyncio
async def test_spawning_survives_a_stored_minimum_above_the_maximum() -> None:
    _, config = _cog(generation_min_amount=200, generation_max_amount=100, generation_chance=1.0)
    config._global.update(currency_generation_enabled=True, generation_channels=[5], currency_symbol="$")
    generation = CurrencyGeneration(MagicMock(), config, MagicMock())
    await generation.refresh_config_cache()
    generation._create_plant = AsyncMock(return_value=1)  # type: ignore[method-assign]
    generation._update_plant_message_id = AsyncMock()  # type: ignore[method-assign]

    message = MagicMock(spec=discord.Message)
    message.author = MagicMock(id=7, bot=False)
    message.guild = MagicMock(id=1)
    message.channel = MagicMock(id=5)
    message.channel.send = AsyncMock()
    with patch("unicornia.systems.currency_systems.os.path.exists", return_value=False):
        await generation.process_message(message)

    generation._create_plant.assert_awaited_once()
    amount = generation._create_plant.call_args.args[2]
    assert 100 <= amount <= 200


@pytest.mark.asyncio
async def test_stored_zero_daily_cooldown_still_means_an_hour() -> None:
    _, config = _cog(timely_cooldown=0)
    db = MagicMock()
    db.economy.attempt_timely_claim = AsyncMock(return_value=None)
    db.economy.get_timely_info = AsyncMock(return_value=(None, 0))
    economy = EconomySystem(db, config, MagicMock())

    await economy.claim_timely(MagicMock(id=7))

    assert db.economy.attempt_timely_claim.await_args is not None
    assert db.economy.attempt_timely_claim.await_args.args[:2] == (7, 3600)


@pytest.mark.asyncio
async def test_stored_zero_decay_interval_waits_an_hour_not_a_minute() -> None:
    _, config = _cog(decay_hour_interval=0)
    bot = MagicMock()
    bot.wait_until_ready = AsyncMock()
    decay = CurrencyDecay(MagicMock(), config, bot)
    decay._get_last_decay_from_db = AsyncMock(return_value=0)  # type: ignore[method-assign]
    decay._process_decay = AsyncMock()  # type: ignore[method-assign]
    sleep = AsyncMock(side_effect=asyncio.CancelledError)

    with patch("unicornia.systems.currency_systems.asyncio.sleep", sleep):
        await decay._decay_loop()

    decay._process_decay.assert_awaited_once()
    sleep.assert_awaited_once()
    assert sleep.call_args.args[0] >= 3500
