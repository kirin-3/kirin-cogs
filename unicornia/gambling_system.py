"""
Gambling system for Unicornia
"""

import random
import discord
from typing import Optional, List, Dict, Any, Tuple
from redbot.core import commands
from .database import DatabaseManager


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
            await self.db.update_gambling_stats(game, bet_amount, win_amount, 0)
            await self.db.update_user_bet_stats(user_id, game, bet_amount, win_amount, 0, win_amount)
            await self.db.log_currency_transaction(user_id, "gambling_win", net_gain, f"{game} win")
        else:
            await self.db.update_gambling_stats(game, bet_amount, 0, bet_amount)
            await self.db.update_user_bet_stats(user_id, game, bet_amount, 0, bet_amount, 0)
            await self.db.log_currency_transaction(user_id, "gambling_loss", -bet_amount, f"{game} loss")
            
            # Add to rakeback (5% of losses)
            rakeback_amount = int(bet_amount * 0.05)
            if rakeback_amount > 0:
                await self.db.add_rakeback(user_id, rakeback_amount)
    
    async def betroll(self, user_id: int, amount: int) -> Tuple[bool, Dict[str, Any]]:
        """Play betroll game"""
        # Check if user has enough currency
        balance = await self.db.get_user_currency(user_id)
        if balance < amount:
            return False, {"error": "insufficient_funds", "balance": balance}
        
        # Roll dice
        roll = random.randint(1, 100)
        threshold = random.randint(1, 100)
        
        if roll >= threshold:
            # Win
            win_amount = amount * 2
            await self.db.add_currency(user_id, win_amount - amount, "betroll", f"roll_{roll}", note=f"Betroll win: {roll} >= {threshold}")
            return True, {
                "won": True,
                "roll": roll,
                "threshold": threshold,
                "win_amount": win_amount,
                "profit": win_amount - amount
            }
        else:
            # Lose
            await self.db.remove_currency(user_id, amount, "betroll", f"roll_{roll}", note=f"Betroll loss: {roll} < {threshold}")
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
        
        # Convert to number
        choice_map = {"rock": 0, "r": 0, "paper": 1, "p": 1, "scissors": 2, "s": 2}
        user_choice = choice_map[choice]
        choices = ["🪨 Rock", "📄 Paper", "✂️ Scissors"]
        
        if amount > 0:
            # Check if user has enough currency
            balance = await self.db.get_user_currency(user_id)
            if balance < amount:
                return False, {"error": "insufficient_funds", "balance": balance}
        
        # Bot choice
        bot_choice = random.randint(0, 2)
        
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
                await self.db.add_currency(user_id, win_amount - amount, "rps", f"win_{user_choice}_{bot_choice}", note=f"RPS win: {choices[user_choice]} vs {choices[bot_choice]}")
                return True, {
                    "result": result,
                    "user_choice": choices[user_choice],
                    "bot_choice": choices[bot_choice],
                    "win_amount": win_amount,
                    "profit": win_amount - amount
                }
            elif result == "lose":
                await self.db.remove_currency(user_id, amount, "rps", f"loss_{user_choice}_{bot_choice}", note=f"RPS loss: {choices[user_choice]} vs {choices[bot_choice]}")
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
        # Check if user has enough currency
        balance = await self.db.get_user_currency(user_id)
        if balance < amount:
            return False, {"error": "insufficient_funds", "balance": balance}
        
        # Generate slot results
        rolls = [random.randint(0, 9) for _ in range(3)]
        
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
            await self.db.add_currency(user_id, won_amount - amount, "slots", f"rolls_{rolls[0]}{rolls[1]}{rolls[2]}", note=f"Slots {win_type}: {rolls}")
        else:
            await self.db.remove_currency(user_id, amount, "slots", f"rolls_{rolls[0]}{rolls[1]}{rolls[2]}", note=f"Slots loss: {rolls}")
        
        return True, {
            "rolls": rolls,
            "win_type": win_type,
            "won_amount": won_amount,
            "profit": won_amount - amount if won_amount > 0 else -amount
        }
    
    async def blackjack(self, user_id: int, amount: int) -> Tuple[bool, Dict[str, Any]]:
        """Start a blackjack game"""
        # This would need a more complex implementation with game state management
        # For now, return a placeholder
        return False, {"error": "not_implemented"}
    
    async def lucky_ladder(self, user_id: int, amount: int) -> Tuple[bool, Dict[str, Any]]:
        """Play lucky ladder game"""
        # Check if user has enough currency
        balance = await self.db.get_user_currency(user_id)
        if balance < amount:
            return False, {"error": "insufficient_funds", "balance": balance}
        
        # Lucky ladder has 8 rungs with different multipliers
        multipliers = [2.4, 1.7, 1.5, 1.1, 0.5, 0.3, 0.2, 0.1]
        rung = random.randint(0, 7)
        multiplier = multipliers[rung]
        
        won_amount = int(amount * multiplier)
        
        if won_amount > amount:
            await self.db.add_currency(user_id, won_amount - amount, "lucky_ladder", f"rung_{rung}", note=f"Lucky ladder rung {rung + 1}: {multiplier}x")
        else:
            await self.db.remove_currency(user_id, amount - won_amount, "lucky_ladder", f"rung_{rung}", note=f"Lucky ladder rung {rung + 1}: {multiplier}x")
        
        return True, {
            "rung": rung + 1,
            "multiplier": multiplier,
            "won_amount": won_amount,
            "profit": won_amount - amount
        }
