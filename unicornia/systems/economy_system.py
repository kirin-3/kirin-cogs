"""
Economy and currency system for Unicornia
"""

import discord
from typing import Optional, List, Dict, Any
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_number
from ..database import DatabaseManager


class EconomySystem:
    """Handles currency transactions, banking, and economy features"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
    
    async def get_balance(self, user_id: int) -> tuple[int, int]:
        """Get user's wallet and bank balance"""
        wallet = await self.db.economy.get_user_currency(user_id)
        bank = await self.db.economy.get_bank_balance(user_id)
        return wallet, bank
    
    async def give_currency(self, from_user: int, to_user: int, amount: int, note: str = "") -> bool:
        """Transfer currency between users"""
        if from_user == to_user:
            return False
        
        # Use atomic transfer
        return await self.db.economy.transfer_currency(from_user, to_user, amount, note)
    
    async def award_currency(self, user_id: int, amount: int, note: str = "") -> bool:
        """Award currency to a user (admin only)"""
        # add_currency returns True now (bug fix)
        success = await self.db.economy.add_currency(user_id, amount, "award", "admin", note=note)
        
        if success:
            await self.db.economy.log_currency_transaction(user_id, "award", amount, note)
        return success
    
    async def take_currency(self, user_id: int, amount: int, note: str = "") -> bool:
        """Take currency from a user (admin only)"""
        success = await self.db.economy.remove_currency(user_id, amount, "take", "admin", note=note)
        if success:
            await self.db.economy.log_currency_transaction(user_id, "take", -amount, note)
        return success
    
    async def deposit_bank(self, user_id: int, amount: int) -> bool:
        """Deposit currency to bank"""
        success = await self.db.economy.deposit_bank(user_id, amount)
        if success:
            await self.db.economy.log_currency_transaction(user_id, "bank_deposit", -amount, f"Deposited {amount} to bank")
        return success
    
    async def withdraw_bank(self, user_id: int, amount: int) -> bool:
        """Withdraw currency from bank"""
        success = await self.db.economy.withdraw_bank(user_id, amount)
        if success:
            await self.db.economy.log_currency_transaction(user_id, "bank_withdraw", amount, f"Withdrew {amount} from bank")
        return success
    
    async def get_bank_info(self, user_id: int) -> int:
        """Get bank balance"""
        result = await self.db.economy.get_bank_user(user_id)
        return result[0]
    
    async def claim_timely(self, user: discord.Member) -> tuple[bool, int, int, dict]:
        """Claim daily timely reward with streak tracking"""
        user_id = user.id
        # Get timely info
        last_claim, streak = await self.db.economy.get_timely_info(user_id)
        
        # Check cooldown (24 hours)
        from datetime import datetime, timedelta
        now = datetime.now()
        
        if last_claim:
            try:
                last_claim_dt = datetime.fromisoformat(last_claim)
                if now - last_claim_dt < timedelta(hours=24):
                    # Still on cooldown
                    return False, 0, streak, {}
            except ValueError:
                # If date is invalid, treat as never claimed
                pass
        
        # Calculate new streak
        if last_claim:
            try:
                last_claim_dt = datetime.fromisoformat(last_claim)
                if now - last_claim_dt <= timedelta(hours=48):  # Within 48 hours = maintain streak
                    new_streak = streak + 1
                else:
                    new_streak = 1  # Reset streak
            except ValueError:
                # If date is invalid, treat as never claimed
                new_streak = 1
        else:
            new_streak = 1
        
        # Calculate reward amount (base + streak bonus)
        base_amount = await self.config.timely_amount()
        streak_bonus = min(new_streak * 10, 300)  # Max 300 bonus
        
        # Supporter Bonus
        supporter_bonus = 0
        supporter_role_id = 700121551483437128
        if any(r.id == supporter_role_id for r in user.roles):
            supporter_bonus = 100
            
        # Server Booster Bonus
        booster_bonus = 0
        if user.premium_since is not None:
            booster_bonus = 100
        
        total_amount = base_amount + streak_bonus + supporter_bonus + booster_bonus
        
        breakdown = {
            "base": base_amount,
            "streak": streak_bonus,
            "supporter": supporter_bonus,
            "booster": booster_bonus
        }
        
        # Award currency
        await self.db.economy.add_currency(user_id, total_amount, "timely", "system")
        await self.db.economy.update_timely_claim(user_id, new_streak)
        await self.db.economy.log_currency_transaction(user_id, "timely", total_amount, f"Daily reward (streak: {new_streak})")
        
        return True, total_amount, new_streak, breakdown
    
    async def get_leaderboard(self, limit: int = 10, offset: int = 0):
        """Get currency leaderboard"""
        return await self.db.economy.get_top_currency_users(limit, offset)

    async def get_filtered_leaderboard(self, guild: discord.Guild):
        """Get filtered currency leaderboard for a guild (only current members)"""
        all_users = await self.db.economy.get_all_users_currency()
        
        filtered_users = []
        for user_id, balance in all_users:
            member = guild.get_member(user_id)
            if member:
                filtered_users.append((user_id, balance))
                
        return filtered_users
    
    async def get_transaction_history(self, user_id: int, limit: int = 50):
        """Get user's transaction history"""
        return await self.db.economy.get_currency_transactions(user_id, limit)
    
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
            return await self.db.economy.get_user_bet_stats(user_id)
        else:
            # Return global stats - would need to implement in database
            return []
    
    async def get_rakeback_info(self, user_id: int) -> int:
        """Get user's rakeback balance"""
        return await self.db.economy.get_rakeback_balance(user_id)
    
    async def claim_rakeback(self, user_id: int) -> int:
        """Claim rakeback balance"""
        balance = await self.db.economy.claim_rakeback(user_id)
        if balance > 0:
            await self.db.economy.add_currency(user_id, balance, "rakeback", "system")
            await self.db.economy.log_currency_transaction(user_id, "rakeback", balance, "Claimed rakeback")
        return balance