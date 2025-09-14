"""
Economy and currency system for Unicornia
"""

import discord
from typing import Optional, List, Dict, Any
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_number
from .database import DatabaseManager


class EconomySystem:
    """Handles currency transactions, banking, and economy features"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
    
    async def get_balance(self, user_id: int) -> tuple[int, int]:
        """Get user's wallet and bank balance"""
        wallet = await self.db.get_user_currency(user_id)
        bank = await self.db.get_bank_balance(user_id)
        return wallet, bank
    
    async def give_currency(self, from_user: int, to_user: int, amount: int, note: str = "") -> bool:
        """Transfer currency between users"""
        if from_user == to_user:
            return False
        
        # Check if sender has enough currency
        sender_balance = await self.db.get_user_currency(from_user)
        if sender_balance < amount:
            return False
        
        # Transfer currency
        success = await self.db.remove_currency(from_user, amount, "give", str(to_user), to_user, note)
        if not success:
            return False
        
        await self.db.add_currency(to_user, amount, "receive", str(from_user), from_user, note)
        
        # Log transactions
        await self.db.log_currency_transaction(from_user, "give", -amount, f"Given to user {to_user}: {note}", to_user)
        await self.db.log_currency_transaction(to_user, "receive", amount, f"Received from user {from_user}: {note}", from_user)
        
        return True
    
    async def award_currency(self, user_id: int, amount: int, note: str = "") -> bool:
        """Award currency to a user (admin only)"""
        success = await self.db.add_currency(user_id, amount, "award", "admin", note=note)
        if success:
            await self.db.log_currency_transaction(user_id, "award", amount, note)
        return success
    
    async def take_currency(self, user_id: int, amount: int, note: str = "") -> bool:
        """Take currency from a user (admin only)"""
        success = await self.db.remove_currency(user_id, amount, "take", "admin", note=note)
        if success:
            await self.db.log_currency_transaction(user_id, "take", -amount, note)
        return success
    
    async def deposit_bank(self, user_id: int, amount: int) -> bool:
        """Deposit currency to bank"""
        success = await self.db.deposit_bank(user_id, amount)
        if success:
            await self.db.log_currency_transaction(user_id, "bank_deposit", -amount, f"Deposited {amount} to bank")
        return success
    
    async def withdraw_bank(self, user_id: int, amount: int) -> bool:
        """Withdraw currency from bank"""
        success = await self.db.withdraw_bank(user_id, amount)
        if success:
            await self.db.log_currency_transaction(user_id, "bank_withdraw", amount, f"Withdrew {amount} from bank")
        return success
    
    async def get_bank_info(self, user_id: int) -> tuple[int, float]:
        """Get bank balance and interest rate"""
        return await self.db.get_bank_user(user_id)
    
    async def claim_timely(self, user_id: int) -> tuple[bool, int, int]:
        """Claim daily timely reward with streak tracking"""
        # Get timely info
        last_claim, streak = await self.db.get_timely_info(user_id)
        
        # Check cooldown (24 hours)
        from datetime import datetime, timedelta
        now = datetime.now()
        
        if last_claim:
            last_claim_dt = datetime.fromisoformat(last_claim)
            if now - last_claim_dt < timedelta(hours=24):
                # Still on cooldown
                return False, 0, streak
        
        # Calculate new streak
        if last_claim:
            last_claim_dt = datetime.fromisoformat(last_claim)
            if now - last_claim_dt <= timedelta(hours=48):  # Within 48 hours = maintain streak
                new_streak = streak + 1
            else:
                new_streak = 1  # Reset streak
        else:
            new_streak = 1
        
        # Calculate reward amount (base + streak bonus)
        base_amount = await self.config.timely_amount()
        streak_bonus = min(new_streak * 10, 500)  # Max 500 bonus
        total_amount = base_amount + streak_bonus
        
        # Award currency
        await self.db.add_currency(user_id, total_amount, "timely", "system")
        await self.db.update_timely_claim(user_id, new_streak)
        await self.db.log_currency_transaction(user_id, "timely", total_amount, f"Daily reward (streak: {new_streak})")
        
        return True, total_amount, new_streak
    
    async def get_leaderboard(self, limit: int = 10, offset: int = 0):
        """Get currency leaderboard"""
        return await self.db.get_top_currency_users(limit, offset)
    
    async def get_transaction_history(self, user_id: int, limit: int = 50):
        """Get user's transaction history"""
        return await self.db.get_currency_transactions(user_id, limit)
    
    async def process_interest(self):
        """Process bank interest for all users (background task)"""
        try:
            # This would be called periodically to award interest
            # For now, we'll implement a simple version
            pass
        except Exception as e:
            print(f"Error processing interest: {e}")
    
    async def get_gambling_stats(self, user_id: int = None):
        """Get gambling statistics"""
        if user_id:
            return await self.db.get_user_bet_stats(user_id)
        else:
            # Return global stats - would need to implement in database
            return []
    
    async def get_rakeback_info(self, user_id: int) -> int:
        """Get user's rakeback balance"""
        return await self.db.get_rakeback_balance(user_id)
    
    async def claim_rakeback(self, user_id: int) -> int:
        """Claim rakeback balance"""
        balance = await self.db.claim_rakeback(user_id)
        if balance > 0:
            await self.db.add_currency(user_id, balance, "rakeback", "system")
            await self.db.log_currency_transaction(user_id, "rakeback", balance, "Claimed rakeback")
        return balance
