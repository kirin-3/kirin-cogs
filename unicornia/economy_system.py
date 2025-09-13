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
        return True
    
    async def award_currency(self, user_id: int, amount: int, note: str = "") -> bool:
        """Award currency to a user (admin only)"""
        await self.db.add_currency(user_id, amount, "award", "admin", note=note)
        return True
    
    async def take_currency(self, user_id: int, amount: int, note: str = "") -> bool:
        """Take currency from a user (admin only)"""
        return await self.db.remove_currency(user_id, amount, "take", "admin", note=note)
    
    async def deposit_bank(self, user_id: int, amount: int) -> bool:
        """Deposit currency to bank"""
        return await self.db.deposit_bank(user_id, amount)
    
    async def withdraw_bank(self, user_id: int, amount: int) -> bool:
        """Withdraw currency from bank"""
        return await self.db.withdraw_bank(user_id, amount)
    
    async def claim_timely(self, user_id: int) -> bool:
        """Claim daily timely reward"""
        amount = await self.config.timely_amount()
        cooldown = await self.config.timely_cooldown()
        return await self.db.claim_timely(user_id, amount, cooldown)
    
    async def get_leaderboard(self, limit: int = 10, offset: int = 0):
        """Get currency leaderboard"""
        return await self.db.get_top_currency_users(limit, offset)
    
    async def get_transaction_history(self, user_id: int, limit: int = 10):
        """Get user's transaction history"""
        # This would need to be implemented in the database module
        pass
