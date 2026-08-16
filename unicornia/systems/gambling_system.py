"""
Gambling system for Unicornia
"""

import asyncio
import contextlib
import secrets
from typing import Any, TypeAlias

import discord
from discord import ui
from redbot.core import commands

from ..database import DatabaseManager
from ..db.economy import OUTCOME_INSUFFICIENT_FUNDS, OUTCOME_RESERVED
from ..gambling import (
    betflip_multiplier,
    betroll_multiplier,
    blackjack_natural_multiplier,
    calculate_blackjack_hand,
    lucky_ladder_multiplier,
    rps_multiplier,
    slots_multiplier,
    slots_win_type,
)
from ..views import MinesView

_GamblingResult: TypeAlias = dict[str, Any]


def _new_game_key(game: str, user_id: int) -> str:
    """Stable, unique operation key for one game invocation."""
    return f"{game}:{user_id}:{secrets.token_hex(8)}"


class SpectatorWagerModal(ui.Modal):
    """Collect one whole spectator stake for a fixed side."""

    amount = ui.TextInput(label="Stake amount", placeholder="Enter a whole number", min_length=1, max_length=12)

    def __init__(self, game_view: "BlackjackView", side: str):
        super().__init__(title=f"Bet player {side}s")
        self.game_view = game_view
        self.side = side

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            amount = int(str(self.amount.value).replace(",", ""))
        except ValueError:
            await interaction.response.send_message("Enter a valid whole-number stake.", ephemeral=True)
            return
        message = await self.game_view.place_spectator_wager(interaction, self.side, amount)
        await interaction.response.send_message(message, ephemeral=True)


class BlackjackView(ui.View):
    def __init__(
        self,
        ctx,
        system,
        user_id,
        amount,
        user_hand,
        dealer_hand,
        deck,
        currency_symbol,
        operation_key: str,
        market_id: int | None = None,
    ):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.system = system
        self.user_id = user_id
        self.amount = amount
        self.user_hand = user_hand
        self.dealer_hand = dealer_hand
        self.deck = deck
        self.currency_symbol = currency_symbol
        self.operation_key = operation_key
        self.market_id = market_id
        self.market_closed = market_id is None
        self.message: discord.Message | None = None
        self.finished = False
        self._settle_lock = asyncio.Lock()
        self.end_time = discord.utils.utcnow().timestamp() + 60

    async def _try_begin_finalize(self) -> bool:
        """Claim the right to finalize this game exactly once."""
        async with self._settle_lock:
            if self.finished:
                return False
            self.finished = True
            return True

    def calculate_hand(self, hand):
        return calculate_blackjack_hand(hand)

    def get_embed(self, result_text=None, color=discord.Color.blue()):
        user_total = self.calculate_hand(self.user_hand)

        if self.finished:
            dealer_total = self.calculate_hand(self.dealer_hand)
            dealer_display = f"{self.dealer_hand} ({dealer_total})"
        else:
            dealer_display = f"[{self.dealer_hand[0]}, ?]"

        description = result_text or f"Time remaining: <t:{int(self.end_time)}:R>"
        embed = discord.Embed(title="🃏 Blackjack", description=description, color=color)
        embed.add_field(name="Your Hand", value=f"{self.user_hand} ({user_total})", inline=True)
        embed.add_field(name="Dealer Hand", value=dealer_display, inline=True)

        if result_text:
            embed.title = "🃏 Blackjack Result"

        return embed

    async def on_timeout(self):
        if not await self._try_begin_finalize():
            return
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]

        await self.close_spectator_market()

        embed = self.get_embed("Timed out. You stand.", discord.Color.red())
        try:
            if self.message:
                await self.message.edit(embed=embed, view=self)
        except discord.HTTPException:
            pass
        await self.do_stand_logic()

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: ui.Item[Any]) -> None:
        # Abandon the hand safely. Both settlement calls are idempotent, so a
        # failure after either commit cannot turn a completed result into a
        # refund, while a pre-commit failure cannot strand reserved currency.
        self.finished = True
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        with contextlib.suppress(Exception):
            await self.system.db.economy.settle_stake(
                key=self.operation_key,
                payout=self.amount,
                transaction_type="gambling_refund",
                extra="blackjack_error",
                note="Refunded abandoned blackjack hand",
                result={"result": "error_refund"},
                exclude_from_rtp=True,
            )
        if self.market_id is not None:
            with contextlib.suppress(Exception):
                await self.system.db.economy.settle_spectator_market(self.market_id, None)
        self.stop()
        await super().on_error(interaction, error, item)

    async def close_spectator_market(self) -> None:
        if self.market_id is None or self.market_closed:
            return
        await self.system.db.economy.close_spectator_market(self.market_id)
        self.market_closed = True

    async def settle_spectator_market(self, winning_side: str | None) -> None:
        if self.market_id is None:
            return
        await self.system.db.economy.settle_spectator_market(self.market_id, winning_side)

    async def place_spectator_wager(self, interaction: discord.Interaction, side: str, amount: int) -> str:
        if self.market_id is None or self.market_closed or self.finished:
            return "This market is closed."
        limit_error = await self.system._check_limits(amount)
        if limit_error:
            return limit_error
        outcome = await self.system.db.economy.place_spectator_bet(
            market_id=self.market_id,
            player_id=self.user_id,
            user_id=interaction.user.id,
            side=side,
            amount=amount,
            market_cap=self.amount,
            guild_id=self.ctx.guild.id if self.ctx.guild else None,
        )
        state = outcome["state"]
        if state == OUTCOME_RESERVED:
            return (
                f"Wager accepted: {self.currency_symbol}{amount:,} on player {side}s. "
                f"Your position is now {self.currency_symbol}{int(outcome['position']):,}."
            )
        if state == "full":
            return "The spectator market is full; your wager was not accepted."
        if state == "opposite_side":
            return "You already hold the other side of this market."
        if state == "player_forbidden":
            return "You cannot wager on your own blackjack hand."
        if state == OUTCOME_INSUFFICIENT_FUNDS:
            return f"You cannot afford that wager. Your balance is {self.currency_symbol}{int(outcome['balance']):,}."
        return "This market is closed."

    @ui.button(label="Hit", style=discord.ButtonStyle.primary, row=0)
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your game!", ephemeral=True)
            return

        if self.finished:
            await interaction.response.send_message("This game is already over.", ephemeral=True)
            return

        await self.close_spectator_market()

        self.user_hand.append(self.deck.pop())
        user_total = self.calculate_hand(self.user_hand)

        if user_total > 21:
            # Bust
            if not await self._try_begin_finalize():
                await interaction.response.send_message("This game is already over.", ephemeral=True)
                return
            for child in self.children:
                child.disabled = True  # type: ignore[attr-defined]

            await self.system.db.economy.settle_stake(
                key=self.operation_key,
                payout=0,
                transaction_type="blackjack",
                note="Blackjack bust",
                result={"result": "bust", "user_total": user_total},
            )
            await self.settle_spectator_market("lose")
            embed = self.get_embed(
                f"Busted with {user_total}! You lost {self.currency_symbol}{self.amount:,}.", discord.Color.red()
            )
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
        else:
            embed = self.get_embed()
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Stand", style=discord.ButtonStyle.secondary, row=0)
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your game!", ephemeral=True)
            return

        if self.finished:
            await interaction.response.send_message("This game is already over.", ephemeral=True)
            return

        await self.close_spectator_market()
        await interaction.response.defer()
        if not await self._try_begin_finalize():
            return
        await self.do_stand_logic()

    @ui.button(label="Bet: Player Wins", style=discord.ButtonStyle.success, row=1)
    async def wager_win(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.user.id == self.user_id:
            await interaction.response.send_message("You cannot wager on your own hand.", ephemeral=True)
            return
        if self.market_closed or self.finished:
            await interaction.response.send_message("This market is closed.", ephemeral=True)
            return
        await interaction.response.send_modal(SpectatorWagerModal(self, "win"))

    @ui.button(label="Bet: Player Loses", style=discord.ButtonStyle.danger, row=1)
    async def wager_lose(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.user.id == self.user_id:
            await interaction.response.send_message("You cannot wager on your own hand.", ephemeral=True)
            return
        if self.market_closed or self.finished:
            await interaction.response.send_message("This market is closed.", ephemeral=True)
            return
        await interaction.response.send_modal(SpectatorWagerModal(self, "lose"))

    async def do_stand_logic(self):
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]

        # Dealer turn
        dealer_total = self.calculate_hand(self.dealer_hand)
        while dealer_total < 17:
            self.dealer_hand.append(self.deck.pop())
            dealer_total = self.calculate_hand(self.dealer_hand)

        user_total = self.calculate_hand(self.user_hand)

        win = False
        tie = False
        result_text = ""

        if dealer_total > 21:
            win = True
            result_text = f"Dealer busted with {dealer_total}!"
        elif dealer_total > user_total:
            win = False
            result_text = f"Dealer has {dealer_total}, you have {user_total}."
        elif dealer_total < user_total:
            win = True
            result_text = f"You have {user_total}, dealer has {dealer_total}."
        else:
            tie = True
            result_text = f"Push! Both have {user_total}."

        color = discord.Color.green() if win else (discord.Color.gold() if tie else discord.Color.red())

        if win:
            win_amount = self.amount * 2
            await self.system.db.economy.settle_stake(
                key=self.operation_key,
                payout=win_amount,
                transaction_type="blackjack",
                note="Blackjack Win",
                result={"result": "win", "win_amount": win_amount},
            )
            result_text += f"\nYou won {self.currency_symbol}{win_amount:,}!"
            spectator_side = "win"
        elif tie:
            await self.system.db.economy.settle_stake(
                key=self.operation_key,
                payout=self.amount,
                transaction_type="blackjack",
                note="Blackjack Push",
                result={"result": "push"},
            )
            result_text += "\nYour bet was returned."
            spectator_side = None
        else:
            await self.system.db.economy.settle_stake(
                key=self.operation_key,
                payout=0,
                transaction_type="blackjack",
                note="Blackjack loss",
                result={"result": "loss"},
            )
            result_text += f"\nYou lost {self.currency_symbol}{self.amount:,}."
            spectator_side = "lose"

        await self.settle_spectator_market(spectator_side)

        embed = self.get_embed(result_text, color)
        if self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(embed=embed, view=self)
        self.stop()


class DuelChallengeView(ui.View):
    """Accept/decline gate for a named duel opponent."""

    def __init__(self, ctx, system, opponent: discord.Member, amount: int):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.system = system
        self.challenger = ctx.author
        self.opponent = opponent
        self.amount = amount
        self.message: discord.Message | None = None
        self.finished = False

    async def _finish(self) -> bool:
        if self.finished:
            return False
        self.finished = True
        return True

    async def on_timeout(self) -> None:
        if not await self._finish():
            return
        await self.system.release_duel_users(self.challenger.id, self.opponent.id)
        if self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(content="Duel challenge expired.", view=None)

    @ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("Only the challenged player can accept.", ephemeral=True)
            return
        if not await self._finish():
            await interaction.response.send_message("This challenge is no longer pending.", ephemeral=True)
            return

        duel_id = secrets.token_hex(8)
        challenger_key = f"duel:{duel_id}:{self.challenger.id}"
        opponent_key = f"duel:{duel_id}:{self.opponent.id}"
        stakes = {challenger_key: "challenger", opponent_key: "opponent"}
        stakes_reserved = False
        try:
            outcomes = await self.system.db.economy.reserve_stakes(
                stakes=(
                    (challenger_key, self.challenger.id, self.amount),
                    (opponent_key, self.opponent.id, self.amount),
                ),
                game="duel",
                guild_id=self.ctx.guild.id if self.ctx.guild else None,
                note="PvP duel stake",
            )
            if len(outcomes) != 2 or any(outcome.state != OUTCOME_RESERVED for outcome in outcomes.values()):
                failed = next(iter(outcomes.values()))
                await self.system.release_duel_users(self.challenger.id, self.opponent.id)
                await interaction.response.edit_message(
                    content=(
                        f"Duel cancelled: <@{failed.key.rsplit(':', 1)[-1]}> cannot fund the stake."
                        if failed.state == OUTCOME_INSUFFICIENT_FUNDS
                        else "Duel cancelled because its stakes could not be reserved."
                    ),
                    view=None,
                )
                self.stop()
                return

            stakes_reserved = True
            duel = DuelThrowView(
                self.system,
                duel_id,
                self.challenger,
                self.opponent,
                self.amount,
                stakes,
            )
            duel.message = interaction.message
            await interaction.response.edit_message(content=duel.prompt, view=duel)
            self.stop()
        except Exception:
            if stakes_reserved:
                # If publishing the throw controls fails after both debits
                # commit, abandon the duel by refunding the whole pool now.
                # The startup sweeper remains the final crash-recovery layer.
                with contextlib.suppress(Exception):
                    await self.system.db.economy.settle_pool(
                        settlement_id=f"duel:{duel_id}",
                        stakes=stakes,
                        winning_side=None,
                        game="duel",
                        void=True,
                        note="PvP duel setup failure refund",
                    )
            await self.system.release_duel_users(self.challenger.id, self.opponent.id)
            self.stop()
            raise

    @ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("Only the challenged player can decline.", ephemeral=True)
            return
        if not await self._finish():
            await interaction.response.send_message("This challenge is no longer pending.", ephemeral=True)
            return
        await self.system.release_duel_users(self.challenger.id, self.opponent.id)
        await interaction.response.edit_message(content="Duel declined.", view=None)
        self.stop()


class DuelThrowView(ui.View):
    """Collect two concealed RPS throws and settle at most once."""

    choices = ("rock", "paper", "scissors")

    def __init__(
        self,
        system,
        duel_id: str,
        challenger: discord.Member,
        opponent: discord.Member,
        amount: int,
        stakes: dict[str, str],
    ):
        super().__init__(timeout=30)
        self.system = system
        self.duel_id = duel_id
        self.challenger = challenger
        self.opponent = opponent
        self.amount = amount
        self.stakes = stakes
        self.round = 1
        self.throws: dict[int, str] = {}
        self.message: discord.Message | None = None
        self._lock = asyncio.Lock()
        for choice, emoji in (("rock", "🪨"), ("paper", "📄"), ("scissors", "✂️")):
            button = ui.Button(label=choice.title(), emoji=emoji, style=discord.ButtonStyle.primary)
            button.callback = self._choice_callback(choice)
            self.add_item(button)

    @property
    def prompt(self) -> str:
        return (
            f"Round {self.round}/3 — {self.challenger.mention} vs {self.opponent.mention}. "
            "Choose privately; throws are revealed only after both commit."
        )

    def _choice_callback(self, choice: str):
        async def callback(interaction: discord.Interaction) -> None:
            if interaction.user.id not in {self.challenger.id, self.opponent.id}:
                await interaction.response.send_message("You are not a player in this duel.", ephemeral=True)
                return
            async with self._lock:
                if interaction.user.id in self.throws:
                    await interaction.response.send_message("Your throw is already locked in.", ephemeral=True)
                    return
                self.throws[interaction.user.id] = choice
                await interaction.response.send_message(f"Locked in: **{choice}**.", ephemeral=True)
                if len(self.throws) == 2:
                    await self._resolve_round()

        return callback

    @staticmethod
    def _winner(first: str, second: str) -> int:
        if first == second:
            return 0
        return 1 if (first, second) in {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")} else 2

    async def _resolve_round(self) -> None:
        challenger_throw = self.throws[self.challenger.id]
        opponent_throw = self.throws[self.opponent.id]
        winner = self._winner(challenger_throw, opponent_throw)
        reveal = f"{self.challenger.mention}: **{challenger_throw}** — {self.opponent.mention}: **{opponent_throw}**"
        if winner == 0 and self.round < 3:
            self.round += 1
            self.throws.clear()
            self.timeout = 30
            if self.message:
                await self.message.edit(content=f"{reveal}\nDraw! {self.prompt}", view=self)
            return
        if winner == 0:
            await self._settle(None, f"{reveal}\nThird consecutive draw — both stakes refunded.")
        else:
            winning_side = "challenger" if winner == 1 else "opponent"
            winner_member = self.challenger if winner == 1 else self.opponent
            await self._settle(winning_side, f"{reveal}\n{winner_member.mention} wins the duel!")

    async def on_timeout(self) -> None:
        async with self._lock:
            if len(self.throws) == 1:
                thrower_id = next(iter(self.throws))
                side = "challenger" if thrower_id == self.challenger.id else "opponent"
                member = self.challenger if thrower_id == self.challenger.id else self.opponent
                await self._settle(side, f"{member.mention} wins by forfeit.")
            else:
                await self._settle(None, "Neither player threw in time — both stakes refunded.")

    async def _settle(self, winning_side: str | None, content: str) -> None:
        try:
            await self.system.db.economy.settle_pool(
                settlement_id=f"duel:{self.duel_id}",
                stakes=self.stakes,
                winning_side=winning_side,
                game="duel",
                void=winning_side is None,
                note="PvP duel settlement",
            )
            if self.message:
                with contextlib.suppress(discord.HTTPException):
                    await self.message.edit(content=content, view=None)
        except Exception:
            # A failed decisive settlement must not strand both stakes after
            # this view releases its in-memory locks and stops. Prefer a full
            # refund; the durable id makes this inert if settlement committed.
            with contextlib.suppress(Exception):
                await self.system.db.economy.settle_pool(
                    settlement_id=f"duel:{self.duel_id}",
                    stakes=self.stakes,
                    winning_side=None,
                    game="duel",
                    void=True,
                    note="PvP duel settlement failure refund",
                )
            raise
        finally:
            await self.system.release_duel_users(self.challenger.id, self.opponent.id)
            self.stop()


class GamblingSystem:
    """Handles all gambling games and features"""

    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
        self._duel_users: set[int] = set()
        self._duel_lock = asyncio.Lock()

    async def claim_duel_users(self, challenger_id: int, opponent_id: int) -> bool:
        async with self._duel_lock:
            if challenger_id in self._duel_users or opponent_id in self._duel_users:
                return False
            self._duel_users.update((challenger_id, opponent_id))
            return True

    async def release_duel_users(self, challenger_id: int, opponent_id: int) -> None:
        async with self._duel_lock:
            self._duel_users.discard(challenger_id)
            self._duel_users.discard(opponent_id)

    async def challenge_duel(self, ctx: commands.Context, opponent: discord.Member, amount: int) -> str | None:
        """Validate and publish one bounded duel challenge."""
        if ctx.author.id == opponent.id:
            return "You cannot duel yourself."
        if opponent.bot:
            return "Bots cannot be challenged to duels."
        limit_error = await self._check_limits(amount)
        if limit_error:
            return limit_error
        if not await self.claim_duel_users(ctx.author.id, opponent.id):
            return "One of those players already has a pending or active duel."
        try:
            view = DuelChallengeView(ctx, self, opponent, amount)
            symbol = await self.config.currency_symbol()
            view.message = await ctx.send(
                f"{opponent.mention}, {ctx.author.mention} challenges you to a duel for {symbol}{amount:,} each.",
                view=view,
            )
        except Exception:
            await self.release_duel_users(ctx.author.id, opponent.id)
            raise
        return None

    async def _check_limits(self, amount: int) -> str | None:
        """Check if bet is within limits"""
        min_bet = await self.config.gambling_min_bet()
        max_bet = await self.config.gambling_max_bet()

        if amount < min_bet:
            return f"Bet must be at least {min_bet}."
        if amount > max_bet:
            return f"Bet cannot exceed {max_bet}."
        return None

    async def betroll(self, user_id: int, amount: int) -> tuple[bool, _GamblingResult]:
        """Play betroll game.

        Args:
            user_id: Discord user ID.
            amount: Bet amount.

        Returns:
            Tuple of (success, result data).
        """
        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            return False, {"error": limit_error}

        # Reserve the stake atomically before producing the outcome
        key = _new_game_key("betroll", user_id)
        reserved = await self.db.economy.reserve_stake(key=key, user_id=user_id, amount=amount, game="betroll")
        if reserved.state == OUTCOME_INSUFFICIENT_FUNDS:
            return False, {"error": "insufficient_funds", "balance": reserved.new_balance}

        # Roll dice
        roll = secrets.randbelow(100) + 1
        multiplier = betroll_multiplier(roll)

        if multiplier > 0:
            # Win
            win_amount = int(amount * multiplier)
            await self.db.economy.settle_stake(
                key=key,
                payout=win_amount,
                transaction_type="betroll",
                extra=f"roll_{roll}",
                note=f"Betroll tier win: {roll} ({multiplier:g}x)",
                result={"won": True, "roll": roll, "multiplier": multiplier},
            )
            return True, {
                "won": True,
                "roll": roll,
                "multiplier": multiplier,
                "win_amount": win_amount,
                "profit": win_amount - amount,
            }
        else:
            # Lose
            await self.db.economy.settle_stake(
                key=key,
                payout=0,
                transaction_type="betroll",
                extra=f"roll_{roll}",
                note=f"Betroll loss: {roll}",
                result={"won": False, "roll": roll, "multiplier": 0.0},
            )
            return True, {"won": False, "roll": roll, "multiplier": 0.0, "loss_amount": amount}

    async def rock_paper_scissors(self, user_id: int, choice: str, amount: int = 0) -> tuple[bool, _GamblingResult]:
        """Play rock paper scissors.

        Args:
            user_id: Discord user ID.
            choice: User's weapon choice.
            amount: Bet amount (optional).

        Returns:
            Tuple of (success, result data).
        """
        choice = choice.lower()
        if choice not in ["rock", "paper", "scissors", "r", "p", "s"]:
            return False, {"error": "invalid_choice"}

        key: str | None = None
        if amount > 0:
            # Check limits
            limit_error = await self._check_limits(amount)
            if limit_error:
                return False, {"error": limit_error}

            # Reserve the stake atomically before producing the outcome
            key = _new_game_key("rps", user_id)
            reserved = await self.db.economy.reserve_stake(key=key, user_id=user_id, amount=amount, game="rps")
            if reserved.state == OUTCOME_INSUFFICIENT_FUNDS:
                return False, {"error": "insufficient_funds", "balance": reserved.new_balance}

        # Convert to number
        choice_map = {"rock": 0, "r": 0, "paper": 1, "p": 1, "scissors": 2, "s": 2}
        user_choice = choice_map[choice]
        choices = ["🪨 Rock", "📄 Paper", "✂️ Scissors"]

        # Bot choice
        bot_choice = secrets.randbelow(3)

        # Determine winner
        if user_choice == bot_choice:
            result = "draw"
        elif (user_choice - bot_choice) % 3 == 1:
            result = "win"
        else:
            result = "lose"

        if amount > 0 and key is not None:
            if result == "win":
                win_amount = int(amount * rps_multiplier(result))
                await self.db.economy.settle_stake(
                    key=key,
                    payout=win_amount,
                    transaction_type="rps",
                    extra=f"win_{user_choice}_{bot_choice}",
                    note=f"RPS win: {choices[user_choice]} vs {choices[bot_choice]}",
                    result={"result": result},
                )
                return True, {
                    "result": result,
                    "user_choice": choices[user_choice],
                    "bot_choice": choices[bot_choice],
                    "win_amount": win_amount,
                    "profit": win_amount - amount,
                }
            elif result == "lose":
                await self.db.economy.settle_stake(
                    key=key,
                    payout=0,
                    transaction_type="rps",
                    extra=f"loss_{user_choice}_{bot_choice}",
                    note=f"RPS loss: {choices[user_choice]} vs {choices[bot_choice]}",
                    result={"result": result},
                )
                return True, {
                    "result": result,
                    "user_choice": choices[user_choice],
                    "bot_choice": choices[bot_choice],
                    "loss_amount": amount,
                }
            else:
                # Draw: the reserved stake is refunded in full.
                await self.db.economy.settle_stake(
                    key=key,
                    payout=amount,
                    transaction_type="rps",
                    extra=f"draw_{user_choice}_{bot_choice}",
                    note=f"RPS draw: {choices[user_choice]} vs {choices[bot_choice]}",
                    result={"result": result},
                )
                return True, {"result": result, "user_choice": choices[user_choice], "bot_choice": choices[bot_choice]}
        else:
            return True, {"result": result, "user_choice": choices[user_choice], "bot_choice": choices[bot_choice]}

    async def slots(self, user_id: int, amount: int) -> tuple[bool, _GamblingResult]:
        """Play slots game.

        Args:
            user_id: Discord user ID.
            amount: Bet amount.

        Returns:
            Tuple of (success, result data).
        """
        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            return False, {"error": limit_error}

        # Reserve the stake atomically before producing the outcome
        key = _new_game_key("slots", user_id)
        reserved = await self.db.economy.reserve_stake(key=key, user_id=user_id, amount=amount, game="slots")
        if reserved.state == OUTCOME_INSUFFICIENT_FUNDS:
            return False, {"error": "insufficient_funds", "balance": reserved.new_balance}

        # Generate slot results
        rolls = [secrets.randbelow(10) for _ in range(3)]

        multiplier = slots_multiplier(*rolls)
        won_amount = int(amount * multiplier)
        win_type = slots_win_type(*rolls)

        await self.db.economy.settle_stake(
            key=key,
            payout=won_amount,
            transaction_type="slots",
            extra=f"rolls_{rolls[0]}{rolls[1]}{rolls[2]}",
            note=f"Slots {win_type}: {rolls}",
            result={"win_type": win_type, "rolls": rolls, "won_amount": won_amount},
        )

        return True, {
            "rolls": rolls,
            "win_type": win_type,
            "won_amount": won_amount,
            "profit": won_amount - amount if won_amount > 0 else -amount,
        }

    async def play_blackjack(self, ctx: commands.Context, amount: int):
        """Play an interactive blackjack game"""
        user = ctx.author
        user_id = user.id

        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            await ctx.send(f"<a:zz_NoTick:729318761655435355> {limit_error}")
            return

        currency_symbol = await self.config.currency_symbol()

        # Reserve the stake atomically before producing the outcome
        key = _new_game_key("blackjack", user_id)
        reserved = await self.db.economy.reserve_stake(key=key, user_id=user_id, amount=amount, game="blackjack")
        if reserved.state == OUTCOME_INSUFFICIENT_FUNDS:
            await ctx.send(
                f"<a:zz_NoTick:729318761655435355> You don't have enough {currency_symbol}currency. You have {currency_symbol}{reserved.new_balance:,}."
            )
            return

        # Deck logic
        deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4  # 11 is Ace

        # Secure shuffle
        # secrets module doesn't have shuffle, so we implement Fisher-Yates with secrets
        for i in range(len(deck) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            deck[i], deck[j] = deck[j], deck[i]

        user_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]

        user_total = calculate_blackjack_hand(user_hand)
        dealer_total = calculate_blackjack_hand(dealer_hand)

        # Check for natural 21
        natural_multiplier = blackjack_natural_multiplier(user_hand, dealer_hand)
        if natural_multiplier is not None:
            player_natural = user_total == 21
            dealer_natural = dealer_total == 21
            win_amount = int(amount * natural_multiplier)
            await self.db.economy.settle_stake(
                key=key,
                payout=win_amount,
                transaction_type="blackjack",
                note=(
                    "Blackjack natural push"
                    if player_natural and dealer_natural
                    else "Blackjack Natural"
                    if player_natural
                    else "Dealer blackjack natural"
                ),
                result={
                    "result": "push" if player_natural and dealer_natural else "natural" if player_natural else "loss",
                    "win_amount": win_amount,
                },
            )

            embed = discord.Embed(
                title="🃏 Blackjack!",
                description=(
                    "**Both you and the dealer have natural 21. Push!** Your bet was returned."
                    if player_natural and dealer_natural
                    else f"**Natural 21!** You won {currency_symbol}{win_amount:,}!"
                    if player_natural
                    else f"**Dealer natural 21.** You lost {currency_symbol}{amount:,}."
                ),
                color=discord.Color.gold() if player_natural else discord.Color.red(),
            )
            embed.add_field(name="Your Hand", value=f"{user_hand} ({user_total})", inline=True)
            embed.add_field(name="Dealer Hand", value=f"{dealer_hand} ({dealer_total})", inline=True)
            await ctx.send(embed=embed)
            return

        # Create View
        market_id = await self.db.economy.create_spectator_market(key)
        view = BlackjackView(ctx, self, user_id, amount, user_hand, dealer_hand, deck, currency_symbol, key, market_id)
        embed = view.get_embed()
        try:
            view.message = await ctx.send(embed=embed, view=view)
        except Exception:
            with contextlib.suppress(Exception):
                await self.db.economy.settle_stake(
                    key=key,
                    payout=amount,
                    transaction_type="gambling_refund",
                    extra="blackjack_publish_error",
                    note="Refunded unpublished blackjack hand",
                    result={"result": "publish_error_refund"},
                    exclude_from_rtp=True,
                )
            with contextlib.suppress(Exception):
                await self.db.economy.settle_spectator_market(market_id, None)
            raise

    async def bet_flip(self, user_id: int, amount: int, guess: str) -> tuple[bool, _GamblingResult]:
        """Play betflip game.

        Args:
            user_id: Discord user ID.
            amount: Bet amount.
            guess: Heads or Tails.

        Returns:
            Tuple of (success, result data).
        """
        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            return False, {"error": limit_error}

        # Validate guess
        guess = guess.lower()
        if guess in ["h", "head", "heads"]:
            guess_val = 0
            guess_str = "Heads"
        elif guess in ["t", "tail", "tails"]:
            guess_val = 1
            guess_str = "Tails"
        else:
            return False, {"error": "invalid_guess"}

        # Reserve the stake atomically before producing the outcome
        key = _new_game_key("betflip", user_id)
        reserved = await self.db.economy.reserve_stake(key=key, user_id=user_id, amount=amount, game="betflip")
        if reserved.state == OUTCOME_INSUFFICIENT_FUNDS:
            return False, {"error": "insufficient_funds", "balance": reserved.new_balance}

        # Flip coin
        result_val = secrets.randbelow(2)
        result_str = "Heads" if result_val == 0 else "Tails"

        # Calculate result
        won = guess_val == result_val

        if won:
            win_amount = int(amount * betflip_multiplier(True))
            profit = win_amount - amount

            await self.db.economy.settle_stake(
                key=key,
                payout=win_amount,
                transaction_type="betflip",
                extra=f"{guess_str}_{result_str}",
                note=f"Betflip win: {guess_str} == {result_str}",
                result={"won": True, "result": result_str, "guess": guess_str},
            )

            return True, {
                "won": True,
                "result": result_str,
                "guess": guess_str,
                "win_amount": win_amount,
                "profit": profit,
            }
        else:
            await self.db.economy.settle_stake(
                key=key,
                payout=0,
                transaction_type="betflip",
                extra=f"{guess_str}_{result_str}",
                note=f"Betflip loss: {guess_str} != {result_str}",
                result={"won": False, "result": result_str, "guess": guess_str},
            )

            return True, {"won": False, "result": result_str, "guess": guess_str, "loss_amount": amount}

    async def lucky_ladder(self, user_id: int, amount: int) -> tuple[bool, _GamblingResult]:
        """Play lucky ladder game.

        Args:
            user_id: Discord user ID.
            amount: Bet amount.

        Returns:
            Tuple of (success, result data).
        """
        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            return False, {"error": limit_error}

        # Reserve the stake atomically before producing the outcome
        key = _new_game_key("lucky_ladder", user_id)
        reserved = await self.db.economy.reserve_stake(key=key, user_id=user_id, amount=amount, game="lucky_ladder")
        if reserved.state == OUTCOME_INSUFFICIENT_FUNDS:
            return False, {"error": "insufficient_funds", "balance": reserved.new_balance}

        rung = secrets.randbelow(8)
        multiplier = lucky_ladder_multiplier(rung)

        won_amount = int(amount * multiplier)

        await self.db.economy.settle_stake(
            key=key,
            payout=won_amount,
            transaction_type="lucky_ladder",
            extra=f"rung_{rung}",
            note=f"Lucky ladder rung {rung + 1}: {multiplier}x",
            result={"rung": rung + 1, "multiplier": multiplier, "won_amount": won_amount},
        )

        return True, {
            "rung": rung + 1,
            "multiplier": multiplier,
            "won_amount": won_amount,
            "profit": won_amount - amount,
        }

    async def play_mines(self, ctx: commands.Context, amount: int, mines: int):
        """Play Mines game"""
        user = ctx.author
        user_id = user.id

        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            await ctx.send(f"<a:zz_NoTick:729318761655435355> {limit_error}")
            return

        # Check mines count (1-19 for 20 cells)
        if mines < 1 or mines > 19:
            await ctx.send("<a:zz_NoTick:729318761655435355> Number of mines must be between 1 and 19.")
            return

        currency_symbol = await self.config.currency_symbol()

        # Reserve the stake atomically before producing the outcome
        key = _new_game_key("mines", user_id)
        reserved = await self.db.economy.reserve_stake(key=key, user_id=user_id, amount=amount, game="mines")
        if reserved.state == OUTCOME_INSUFFICIENT_FUNDS:
            await ctx.send(
                f"<a:zz_NoTick:729318761655435355> You don't have enough {currency_symbol}currency. You have {currency_symbol}{reserved.new_balance:,}."
            )
            return

        # Generate mines
        # 20 cells, indices 0-19. We need unique indices.
        mines_indices = set()
        while len(mines_indices) < mines:
            mines_indices.add(secrets.randbelow(20))

        # Create View
        view = MinesView(ctx, self, user_id, amount, mines_indices, 20, currency_symbol, key)

        # Send message
        timer_str = f"<t:{int(view.end_time)}:R>"
        await ctx.send(
            f"**Mines** | Bet: {currency_symbol}{amount:,} | Mines: {mines}\nClick the buttons to reveal safe spots 💎. Avoid the mines 💣!\nTime remaining: {timer_str}",
            view=view,
        )
