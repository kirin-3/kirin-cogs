"""Command-level tests: instant games always reply with the settled result."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from unicornia.commands.gambling import GamblingCommands

ERROR_PREFIX = "Error in"


def _cog(game_result: tuple[bool, dict[str, Any]], *, balance: int = 1_000) -> Any:
    cog = object.__new__(GamblingCommands)
    cog.config = MagicMock()  # type: ignore[attr-defined]
    cog.config.gambling_enabled = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    cog.config.economy_enabled = AsyncMock(return_value=True)  # type: ignore[attr-defined]
    cog.config.currency_symbol = AsyncMock(return_value="$")  # type: ignore[attr-defined]
    cog.db = MagicMock()  # type: ignore[attr-defined]
    cog.db.economy.get_user_currency = AsyncMock(return_value=balance)  # type: ignore[attr-defined]
    cog.gambling_system = MagicMock()  # type: ignore[attr-defined]
    cog.gambling_system.slots = AsyncMock(return_value=game_result)  # type: ignore[attr-defined]
    cog.gambling_system.lucky_ladder = AsyncMock(return_value=game_result)  # type: ignore[attr-defined]
    return cog


def _ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.author.id = 42
    ctx.reply = AsyncMock()
    return ctx


def _reply_text(ctx: MagicMock) -> str:
    ctx.reply.assert_awaited_once()
    return ctx.reply.await_args.args[0]


async def _run(command_name: str, cog: Any, ctx: MagicMock, amount: str) -> str:
    await cast(Any, getattr(GamblingCommands, command_name)).callback(cog, ctx, amount)
    text = _reply_text(ctx)
    assert ERROR_PREFIX not in text
    return text


@pytest.mark.asyncio
async def test_slots_loss_reports_amount_lost() -> None:
    cog = _cog((True, {"rolls": [1, 2, 3], "won_amount": 0, "win_type": "none"}))

    text = await _run("gambling_slots", cog, _ctx(), "500")

    assert "123" in text
    assert "You lost $500." in text


@pytest.mark.asyncio
async def test_slots_all_bet_reports_resolved_amount() -> None:
    cog = _cog((True, {"rolls": [1, 2, 3], "won_amount": 0, "win_type": "none"}), balance=1_234)

    text = await _run("gambling_slots", cog, _ctx(), "all")

    cog.gambling_system.slots.assert_awaited_once_with(42, 1_234)
    assert "You lost $1,234." in text


@pytest.mark.asyncio
async def test_lucky_ladder_win_reports_rung_multiplier_and_win() -> None:
    cog = _cog((True, {"rung": 1, "multiplier": 2.35, "won_amount": 235}))

    text = await _run("gambling_lucky_ladder", cog, _ctx(), "100")

    assert "Rung 1" in text
    assert "2.35x" in text
    assert "You won $235!" in text


@pytest.mark.asyncio
async def test_lucky_ladder_partial_return_reports_net_loss() -> None:
    cog = _cog((True, {"rung": 5, "multiplier": 0.49, "won_amount": 49}))

    text = await _run("gambling_lucky_ladder", cog, _ctx(), "100")

    assert "Rung 5" in text
    assert "0.49x" in text
    assert "You lost $51." in text


@pytest.mark.asyncio
async def test_lucky_ladder_all_bet_uses_resolved_amount() -> None:
    cog = _cog((True, {"rung": 6, "multiplier": 0.29, "won_amount": 580}), balance=2_000)

    text = await _run("gambling_lucky_ladder", cog, _ctx(), "all")

    cog.gambling_system.lucky_ladder.assert_awaited_once_with(42, 2_000)
    assert "You lost $1,420." in text
