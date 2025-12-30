"""
Gambling system for Unicornia
"""

import secrets
import discord
from typing import Optional, List, Dict, Any, Tuple
from redbot.core import commands
from discord import ui
from ..database import DatabaseManager

class BlackjackView(ui.View):
    def __init__(self, ctx, system, user_id, amount, user_hand, dealer_hand, deck, currency_symbol):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.system = system
        self.user_id = user_id
        self.amount = amount
        self.user_hand = user_hand
        self.dealer_hand = dealer_hand
        self.deck = deck
        self.currency_symbol = currency_symbol
        self.message = None
        self.finished = False

    def calculate_hand(self, hand):
        total = sum(hand)
        aces = hand.count(11)
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    def get_embed(self, result_text=None, color=discord.Color.blue()):
        user_total = self.calculate_hand(self.user_hand)
        
        if self.finished:
            dealer_total = self.calculate_hand(self.dealer_hand)
            dealer_display = f"{self.dealer_hand} ({dealer_total})"
        else:
            dealer_display = f"[{self.dealer_hand[0]}, ?]"

        embed = discord.Embed(title="🃏 Blackjack", description=result_text, color=color)
        embed.add_field(name="Your Hand", value=f"{self.user_hand} ({user_total})", inline=True)
        embed.add_field(name="Dealer Hand", value=dealer_display, inline=True)
        
        if result_text:
            embed.title = "🃏 Blackjack Result"
            
        return embed

    async def on_timeout(self):
        if not self.finished:
            self.finished = True
            for child in self.children:
                child.disabled = True
            
            embed = self.get_embed("Timed out. You stand.", discord.Color.red())
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass
            await self.do_stand_logic()

    @ui.button(label="Hit", style=discord.ButtonStyle.primary, row=0)
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your game!", ephemeral=True)
            return

        self.user_hand.append(self.deck.pop())
        user_total = self.calculate_hand(self.user_hand)

        if user_total > 21:
            # Bust
            self.finished = True
            for child in self.children:
                child.disabled = True
            
            await self.system._log_gambling_result(self.user_id, "blackjack", self.amount, False)
            embed = self.get_embed(f"Busted with {user_total}! You lost {self.currency_symbol}{self.amount:,}.", discord.Color.red())
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.HTTPException:
                pass
            self.stop()
        else:
            embed = self.get_embed()
            try:
                await interaction.response.edit_message(embed=embed, view=self)
            except discord.HTTPException:
                pass

    @ui.button(label="Stand", style=discord.ButtonStyle.secondary, row=0)
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your game!", ephemeral=True)
            return

        await interaction.response.defer()
        await self.do_stand_logic()

    async def do_stand_logic(self):
        self.finished = True
        for child in self.children:
            child.disabled = True

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
            await self.system.db.economy.add_currency(self.user_id, win_amount, "blackjack", "win", note="Blackjack Win")
            await self.system._log_gambling_result(self.user_id, "blackjack", self.amount, True, win_amount)
            result_text += f"\nYou won {self.currency_symbol}{win_amount:,}!"
        elif tie:
            await self.system.db.economy.add_currency(self.user_id, self.amount, "blackjack", "tie", note="Blackjack Push")
            result_text += "\nYour bet was returned."
        else:
            await self.system._log_gambling_result(self.user_id, "blackjack", self.amount, False)
            result_text += f"\nYou lost {self.currency_symbol}{self.amount:,}."

        embed = self.get_embed(result_text, color)
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass
        self.stop()


class GamblingSystem:
    """Handles all gambling games and features"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
    
    async def _log_gambling_result(self, user_id: int, game: str, bet_amount: int, won: bool, win_amount: int = 0):
        """Log gambling result and update statistics"""
        if won:
            net_gain = win_amount - bet_amount
            await self.db.economy.update_gambling_stats(game, bet_amount, win_amount, 0)
            await self.db.economy.update_user_bet_stats(user_id, game, bet_amount, win_amount, 0, win_amount)
            await self.db.economy.log_currency_transaction(user_id, "gambling_win", net_gain, f"{game} win")
        else:
            await self.db.economy.update_gambling_stats(game, bet_amount, 0, bet_amount)
            await self.db.economy.update_user_bet_stats(user_id, game, bet_amount, 0, bet_amount, 0)
            await self.db.economy.log_currency_transaction(user_id, "gambling_loss", -bet_amount, f"{game} loss")
            
            # Add to rakeback (5% of losses)
            rakeback_amount = int(bet_amount * 0.05)
            if rakeback_amount > 0:
                await self.db.economy.add_rakeback(user_id, rakeback_amount)
    
    async def _check_limits(self, amount: int) -> Optional[str]:
        """Check if bet is within limits"""
        min_bet = await self.config.gambling_min_bet()
        max_bet = await self.config.gambling_max_bet()
        
        if amount < min_bet:
            return f"Bet must be at least {min_bet}."
        if amount > max_bet:
            return f"Bet cannot exceed {max_bet}."
        return None

    async def betroll(self, user_id: int, amount: int) -> Tuple[bool, Dict[str, Any]]:
        """Play betroll game"""
        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            return False, {"error": limit_error}

        # Check if user has enough currency
        balance = await self.db.economy.get_user_currency(user_id)
        if balance < amount:
            return False, {"error": "insufficient_funds", "balance": balance}
        
        # Roll dice
        roll = secrets.randbelow(100) + 1
        threshold = secrets.randbelow(100) + 1
        
        if roll >= threshold:
            # Win
            win_amount = amount * 2
            await self.db.economy.add_currency(user_id, win_amount - amount, "betroll", f"roll_{roll}", note=f"Betroll win: {roll} >= {threshold}")
            return True, {
                "won": True,
                "roll": roll,
                "threshold": threshold,
                "win_amount": win_amount,
                "profit": win_amount - amount
            }
        else:
            # Lose
            await self.db.economy.remove_currency(user_id, amount, "betroll", f"roll_{roll}", note=f"Betroll loss: {roll} < {threshold}")
            return True, {
                "won": False,
                "roll": roll,
                "threshold": threshold,
                "loss_amount": amount
            }
    
    async def rock_paper_scissors(self, user_id: int, choice: str, amount: int = 0) -> Tuple[bool, Dict[str, Any]]:
        """Play rock paper scissors"""
        choice = choice.lower()
        if choice not in ["rock", "paper", "scissors", "r", "p", "s"]:
            return False, {"error": "invalid_choice"}
        
        if amount > 0:
            # Check limits
            limit_error = await self._check_limits(amount)
            if limit_error:
                return False, {"error": limit_error}

            # Check if user has enough currency
            balance = await self.db.economy.get_user_currency(user_id)
            if balance < amount:
                return False, {"error": "insufficient_funds", "balance": balance}
        
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
        
        if amount > 0:
            if result == "win":
                win_amount = amount * 2
                await self.db.economy.add_currency(user_id, win_amount - amount, "rps", f"win_{user_choice}_{bot_choice}", note=f"RPS win: {choices[user_choice]} vs {choices[bot_choice]}")
                return True, {
                    "result": result,
                    "user_choice": choices[user_choice],
                    "bot_choice": choices[bot_choice],
                    "win_amount": win_amount,
                    "profit": win_amount - amount
                }
            elif result == "lose":
                await self.db.economy.remove_currency(user_id, amount, "rps", f"loss_{user_choice}_{bot_choice}", note=f"RPS loss: {choices[user_choice]} vs {choices[bot_choice]}")
                return True, {
                    "result": result,
                    "user_choice": choices[user_choice],
                    "bot_choice": choices[bot_choice],
                    "loss_amount": amount
                }
            else:
                return True, {
                    "result": result,
                    "user_choice": choices[user_choice],
                    "bot_choice": choices[bot_choice]
                }
        else:
            return True, {
                "result": result,
                "user_choice": choices[user_choice],
                "bot_choice": choices[bot_choice]
            }
    
    async def slots(self, user_id: int, amount: int) -> Tuple[bool, Dict[str, Any]]:
        """Play slots game"""
        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            return False, {"error": limit_error}

        # Check if user has enough currency
        balance = await self.db.economy.get_user_currency(user_id)
        if balance < amount:
            return False, {"error": "insufficient_funds", "balance": balance}
        
        # Generate slot results
        rolls = [secrets.randbelow(10) for _ in range(3)]
        
        # Calculate winnings based on Nadeko's slot logic
        won_amount = 0
        win_type = "lose"
        
        if rolls[0] == rolls[1] == rolls[2] == 9:  # Triple joker
            won_amount = int(amount * 10)
            win_type = "triple_joker"
        elif rolls[0] == rolls[1] == rolls[2]:  # Triple normal
            won_amount = int(amount * 2)
            win_type = "triple_normal"
        elif rolls.count(9) == 2:  # Double joker
            won_amount = int(amount * 1.5)
            win_type = "double_joker"
        elif rolls.count(9) == 1:  # Single joker
            won_amount = int(amount * 1.2)
            win_type = "single_joker"
        
        if won_amount > 0:
            await self.db.economy.add_currency(user_id, won_amount - amount, "slots", f"rolls_{rolls[0]}{rolls[1]}{rolls[2]}", note=f"Slots {win_type}: {rolls}")
        else:
            await self.db.economy.remove_currency(user_id, amount, "slots", f"rolls_{rolls[0]}{rolls[1]}{rolls[2]}", note=f"Slots loss: {rolls}")
        
        return True, {
            "rolls": rolls,
            "win_type": win_type,
            "won_amount": won_amount,
            "profit": won_amount - amount if won_amount > 0 else -amount
        }
    
    async def play_blackjack(self, ctx: commands.Context, amount: int):
        """Play an interactive blackjack game"""
        user = ctx.author
        user_id = user.id
        
        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            await ctx.send(f"❌ {limit_error}")
            return

        # Check balance
        balance = await self.db.economy.get_user_currency(user_id)
        currency_symbol = await self.config.currency_symbol()
        
        if balance < amount:
            await ctx.send(f"❌ You don't have enough {currency_symbol}currency. You have {currency_symbol}{balance:,}.")
            return

        # Deduct bet immediately
        await self.db.economy.remove_currency(user_id, amount, "blackjack", "start", note="Blackjack start")
        
        # Deck logic
        deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4 # 11 is Ace
        
        # Secure shuffle
        # secrets module doesn't have shuffle, so we implement Fisher-Yates with secrets
        for i in range(len(deck) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            deck[i], deck[j] = deck[j], deck[i]
        
        def calculate_hand(hand):
            total = sum(hand)
            aces = hand.count(11)
            while total > 21 and aces:
                total -= 10
                aces -= 1
            return total
            
        user_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]
        
        user_total = calculate_hand(user_hand)
        dealer_total = calculate_hand(dealer_hand)
        
        # Check for natural 21
        if user_total == 21:
            # Instant win 2.5x
            win_amount = int(amount * 2.5)
            await self.db.economy.add_currency(user_id, win_amount, "blackjack", "win", note="Blackjack Natural")
            await self._log_gambling_result(user_id, "blackjack", amount, True, win_amount)
            
            embed = discord.Embed(title="🃏 Blackjack!", description=f"**Natural 21!** You won {currency_symbol}{win_amount:,}!", color=discord.Color.gold())
            embed.add_field(name="Your Hand", value=f"{user_hand} ({user_total})", inline=True)
            embed.add_field(name="Dealer Hand", value=f"{dealer_hand} ({dealer_total})", inline=True)
            await ctx.send(embed=embed)
            return

        # Create View
        view = BlackjackView(ctx, self, user_id, amount, user_hand, dealer_hand, deck, currency_symbol)
        embed = view.get_embed()
        view.message = await ctx.send(embed=embed, view=view)

    async def bet_flip(self, user_id: int, amount: int, guess: str) -> Tuple[bool, Dict[str, Any]]:
        """Play betflip game"""
        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            return False, {"error": limit_error}

        # Validate guess
        guess = guess.lower()
        if guess in ['h', 'head', 'heads']:
            guess_val = 0
            guess_str = "Heads"
        elif guess in ['t', 'tail', 'tails']:
            guess_val = 1
            guess_str = "Tails"
        else:
            return False, {"error": "invalid_guess"}
            
        # Check if user has enough currency
        balance = await self.db.economy.get_user_currency(user_id)
        if balance < amount:
            return False, {"error": "insufficient_funds", "balance": balance}
            
        # Flip coin
        result_val = secrets.randbelow(2)
        result_str = "Heads" if result_val == 0 else "Tails"
        
        # Calculate result
        won = (guess_val == result_val)
        
        if won:
            # 1.95x multiplier (typical Nadeko default)
            win_amount = int(amount * 1.95)
            profit = win_amount - amount
            
            await self.db.economy.add_currency(user_id, profit, "betflip", f"{guess_str}_{result_str}", note=f"Betflip win: {guess_str} == {result_str}")
            await self._log_gambling_result(user_id, "betflip", amount, True, win_amount)
            
            return True, {
                "won": True,
                "result": result_str,
                "guess": guess_str,
                "win_amount": win_amount,
                "profit": profit
            }
        else:
            await self.db.economy.remove_currency(user_id, amount, "betflip", f"{guess_str}_{result_str}", note=f"Betflip loss: {guess_str} != {result_str}")
            await self._log_gambling_result(user_id, "betflip", amount, False)
            
            return True, {
                "won": False,
                "result": result_str,
                "guess": guess_str,
                "loss_amount": amount
            }

    async def lucky_ladder(self, user_id: int, amount: int) -> Tuple[bool, Dict[str, Any]]:
        """Play lucky ladder game"""
        # Check limits
        limit_error = await self._check_limits(amount)
        if limit_error:
            return False, {"error": limit_error}

        # Check if user has enough currency
        balance = await self.db.economy.get_user_currency(user_id)
        if balance < amount:
            return False, {"error": "insufficient_funds", "balance": balance}
        
        # Lucky ladder has 8 rungs with different multipliers
        multipliers = [2.4, 1.7, 1.5, 1.1, 0.5, 0.3, 0.2, 0.1]
        rung = secrets.randbelow(8)
        multiplier = multipliers[rung]
        
        won_amount = int(amount * multiplier)
        
        if won_amount > amount:
            await self.db.economy.add_currency(user_id, won_amount - amount, "lucky_ladder", f"rung_{rung}", note=f"Lucky ladder rung {rung + 1}: {multiplier}x")
        else:
            await self.db.economy.remove_currency(user_id, amount - won_amount, "lucky_ladder", f"rung_{rung}", note=f"Lucky ladder rung {rung + 1}: {multiplier}x")
        
        return True, {
            "rung": rung + 1,
            "multiplier": multiplier,
            "won_amount": won_amount,
            "profit": won_amount - amount
        }