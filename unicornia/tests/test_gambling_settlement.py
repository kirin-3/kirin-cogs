"""Game-level settlement tests for Unicornia gambling (task 3.3).

Covers reserve-before-outcome migration (3.1), per-game locks and finished
guards (3.2), and stable operation keys with double-click, callback/timeout
race, retry, and restart-safe settlement (3.3) — all against a real database.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from redbot.core import Config

from unicornia.database import DatabaseManager
from unicornia.systems.gambling_system import BlackjackView, GamblingSystem
from unicornia.views import MinesView

USER = 2002


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> AsyncGenerator[DatabaseManager, None]:
    manager = DatabaseManager(str(tmp_path / "gambling.db"))
    await manager.connect()
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
def system(db: DatabaseManager) -> GamblingSystem:
    config = MagicMock(spec=Config)
    config.gambling_min_bet = AsyncMock(return_value=1)
    config.gambling_max_bet = AsyncMock(return_value=1_000_000)
    config.currency_symbol = AsyncMock(return_value="$")
    return GamblingSystem(db, config, MagicMock())


async def _log_count(db: DatabaseManager, user_id: int = USER) -> int:
    async with db._get_connection() as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM CurrencyTransactions WHERE UserId = ?", (user_id,))
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


def _interaction(user_id: int = USER) -> MagicMock:
    interaction = MagicMock()
    interaction.user.id = user_id
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.response.is_done = MagicMock(return_value=False)
    return interaction


# ---------------------------------------------------------------------------
# 3.1 One-shot games reserve before outcome and settle through the API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_betroll_win_net_effect(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    with patch("unicornia.systems.gambling_system.secrets.randbelow", return_value=99):
        success, result = await system.betroll(USER, 100)
    assert success and result["won"] is True
    # -100 stake, +1000 payout at the top tier
    assert await db.economy.get_user_currency(USER) == 1400


@pytest.mark.asyncio
async def test_betroll_loss_net_effect(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    with patch("unicornia.systems.gambling_system.secrets.randbelow", return_value=0):
        success, result = await system.betroll(USER, 100)
    assert success and result["won"] is False
    assert await db.economy.get_user_currency(USER) == 400


@pytest.mark.asyncio
async def test_betroll_insufficient_funds_reserves_nothing(db: DatabaseManager, system: GamblingSystem) -> None:
    success, result = await system.betroll(USER, 100)
    assert not success
    assert result["error"] == "insufficient_funds"
    assert result["balance"] == 0
    assert await _log_count(db) == 0


@pytest.mark.asyncio
async def test_slots_triple_joker_payout(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 1000, "test", "test")
    with patch("unicornia.systems.gambling_system.secrets.randbelow", return_value=9):
        success, result = await system.slots(USER, 100)
    assert success and result["win_type"] == "triple_joker"
    # -100 stake, +15000 payout
    assert await db.economy.get_user_currency(USER) == 15900


@pytest.mark.asyncio
async def test_rps_draw_refunds_stake(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    with patch("unicornia.systems.gambling_system.secrets.randbelow", return_value=0):
        success, result = await system.rock_paper_scissors(USER, "rock", 100)
    assert success and result["result"] == "draw"
    assert await db.economy.get_user_currency(USER) == 500


@pytest.mark.asyncio
async def test_settlement_retry_does_not_duplicate_rakeback_or_stats(db: DatabaseManager) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await db.economy.reserve_stake(key="slots:retry", user_id=USER, amount=100, game="slots")

    first = await db.economy.settle_stake(key="slots:retry", payout=0, transaction_type="slots")
    retry = await db.economy.settle_stake(key="slots:retry", payout=0, transaction_type="slots")

    assert first.state == "settled"
    assert retry.state == "duplicate"
    assert await db.economy.get_rakeback_balance(USER) == 5
    assert await db.economy.get_user_bet_stats(USER) == [("slots", 100, 0, 100, 0)]

    async with db._get_connection() as connection:
        row = await (
            await connection.execute(
                "SELECT BetAmount, WinAmount, LossAmount FROM GamblingStats WHERE Feature = 'slots'"
            )
        ).fetchone()
    assert row == (100, 0, 100)


@pytest.mark.asyncio
async def test_betflip_win_records_stats_and_single_rows(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    with patch("unicornia.systems.gambling_system.secrets.randbelow", return_value=0):
        success, result = await system.bet_flip(USER, 100, "heads")
    assert success and result["won"] is True
    # stake row + payout row only (no duplicate gambling_win row)
    assert await _log_count(db) == 3  # 1 setup add + stake + payout


# ---------------------------------------------------------------------------
# 3.2/3.3 Interactive games: locks, guards, stable keys
# ---------------------------------------------------------------------------


def _blackjack_view(system: GamblingSystem, key: str, deck: list[int]) -> BlackjackView:
    return BlackjackView(
        ctx=MagicMock(),
        system=system,
        user_id=USER,
        amount=100,
        user_hand=[10, 9],  # 19
        dealer_hand=[10, 6],  # 16
        deck=deck,
        currency_symbol="$",
        operation_key=key,
    )


@pytest.mark.asyncio
async def test_blackjack_double_click_stand_settles_once(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    reserved = await db.economy.reserve_stake(key="bj:test", user_id=USER, amount=100, game="blackjack")
    assert reserved.state == "reserved"

    view = _blackjack_view(system, "bj:test", deck=[10] * 40)  # dealer busts -> win
    interaction = _interaction()

    await view.stand_button.callback(interaction)
    assert await db.economy.get_user_currency(USER) == 600  # 500 - 100 + 200

    # Second click hits the finished guard and settles nothing more.
    await view.stand_button.callback(interaction)
    interaction.response.send_message.assert_awaited_with("This game is already over.", ephemeral=True)
    assert await db.economy.get_user_currency(USER) == 600


@pytest.mark.asyncio
async def test_blackjack_callback_timeout_race_settles_once(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await db.economy.reserve_stake(key="bj:race", user_id=USER, amount=100, game="blackjack")

    view = _blackjack_view(system, "bj:race", deck=[10] * 40)
    interaction = _interaction()

    await asyncio.gather(view.on_timeout(), view.stand_button.callback(interaction))

    # Exactly one finalization happened despite the race.
    assert await db.economy.get_user_currency(USER) == 600
    op = await db.economy.get_operation("bj:race")
    assert op is not None and op["State"] == "settled"


@pytest.mark.asyncio
async def test_blackjack_bust_settles_loss_once(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await db.economy.reserve_stake(key="bj:bust", user_id=USER, amount=100, game="blackjack")

    view = _blackjack_view(system, "bj:bust", deck=[10] * 40)
    view.user_hand = [10, 8]  # 18, hit -> 28 bust
    interaction = _interaction()

    await view.hit_button.callback(interaction)
    assert await db.economy.get_user_currency(USER) == 400

    # A late timeout cannot double-settle.
    await view.on_timeout()
    assert await db.economy.get_user_currency(USER) == 400


@pytest.mark.asyncio
async def test_blackjack_equal_totals_pushes(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await db.economy.reserve_stake(key="bj:push", user_id=USER, amount=100, game="blackjack")
    view = _blackjack_view(system, "bj:push", deck=[10] * 40)
    view.dealer_hand = [10, 9]

    await view.stand_button.callback(_interaction())

    assert await db.economy.get_user_currency(USER) == 500


@pytest.mark.asyncio
async def test_mines_double_cashout_settles_once(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await db.economy.reserve_stake(key="mines:test", user_id=USER, amount=100, game="mines")

    view = MinesView(MagicMock(), system, USER, 100, {0, 1, 2}, 20, "$", "mines:test")
    view.revealed_indices.add(5)  # one safe reveal -> multiplier > 1
    interaction = _interaction()

    await view.game_over(interaction, True)
    balance_after_win = await db.economy.get_user_currency(USER)
    assert balance_after_win > 400  # payout exceeded the stake

    await view.game_over(interaction, True)
    assert await db.economy.get_user_currency(USER) == balance_after_win


@pytest.mark.asyncio
async def test_mines_full_clear_uses_final_multiplier(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await db.economy.reserve_stake(key="mines:clear", user_id=USER, amount=100, game="mines")
    view = MinesView(MagicMock(), system, USER, 100, {0}, 2, "$", "mines:clear")
    view.revealed_indices.add(1)

    await view.update_game_state(_interaction())

    assert view.current_multiplier == pytest.approx(1.85)
    assert await db.economy.get_user_currency(USER) == 585


@pytest.mark.asyncio
async def test_mines_timeout_settles_loss(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await db.economy.reserve_stake(key="mines:timeout", user_id=USER, amount=100, game="mines")

    view = MinesView(MagicMock(), system, USER, 100, {0, 1, 2}, 20, "$", "mines:timeout")
    await view.on_timeout()

    assert await db.economy.get_user_currency(USER) == 400
    op = await db.economy.get_operation("mines:timeout")
    assert op is not None and op["State"] == "settled"


@pytest.mark.asyncio
async def test_mines_callback_timeout_race_settles_once(db: DatabaseManager, system: GamblingSystem) -> None:
    await db.economy.add_currency(USER, 500, "test", "test")
    await db.economy.reserve_stake(key="mines:race", user_id=USER, amount=100, game="mines")

    view = MinesView(MagicMock(), system, USER, 100, {0, 1, 2}, 20, "$", "mines:race")
    interaction = _interaction()

    await asyncio.gather(view.on_timeout(), view.game_over(interaction, False, 0))

    assert await db.economy.get_user_currency(USER) == 400
    op = await db.economy.get_operation("mines:race")
    assert op is not None and op["State"] == "settled"


@pytest.mark.asyncio
async def test_interactive_game_restart_safe_settlement(tmp_path: Path, system: GamblingSystem) -> None:
    """A reserved game is refunded exactly once during restart reconciliation."""
    manager = DatabaseManager(str(tmp_path / "restart-game.db"))
    await manager.connect()
    await manager.initialize()
    await manager.economy.add_currency(USER, 500, "test", "test")
    await manager.economy.reserve_stake(key="mines:restart", user_id=USER, amount=100, game="mines")
    await manager.close()

    manager2 = DatabaseManager(str(tmp_path / "restart-game.db"))
    await manager2.connect()
    await manager2.initialize()
    assert await manager2.economy.get_user_currency(USER) == 500
    operation = await manager2.economy.get_operation("mines:restart")
    assert operation is not None
    assert operation["State"] == "settled"
    assert operation["Result"] == '{"result": "restart_refund"}'

    # Later callbacks cannot overwrite the recovery result or pay again.
    retry = await manager2.economy.settle_stake(key="mines:restart", payout=100, transaction_type="mines")
    assert retry.state == "duplicate"
    assert retry.result == {"result": "restart_refund"}
    assert await manager2.economy.get_user_currency(USER) == 500

    async with manager2._get_connection() as connection:
        refunds = await (
            await connection.execute(
                "SELECT COUNT(*) FROM CurrencyTransactions WHERE UserId = ? AND Type = 'gambling_refund'",
                (USER,),
            )
        ).fetchone()
    assert refunds == (1,)
    await manager2.close()
