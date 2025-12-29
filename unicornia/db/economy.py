from typing import List, Dict, Any, Tuple
from datetime import datetime

class EconomyRepository:
    """Repository for Economy system database operations"""
    
    def __init__(self, db):
        self.db = db

    # Currency methods
    async def get_user_currency(self, user_id: int) -> int:
        """Get user's wallet currency"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT CurrencyAmount FROM DiscordUser WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def add_currency(self, user_id: int, amount: int, transaction_type: str, extra: str = "", other_id: int = None, note: str = ""):
        """Add currency to user's wallet"""
        async with self.db._get_connection() as db:
            # Update user currency
            await db.execute("""
                INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
            """, (user_id, amount, amount))
            
            # Log transaction
            await db.execute("""
                INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (user_id, amount, transaction_type, extra, other_id, note))
            
            await db.commit()
            return True
    
    async def remove_currency(self, user_id: int, amount: int, transaction_type: str, extra: str = "", other_id: int = None, note: str = "") -> bool:
        """Remove currency from user's wallet"""
        async with self.db._get_connection() as db:
            
            # Atomic update with WHERE clause to prevent race conditions
            cursor = await db.execute("""
                UPDATE DiscordUser
                SET CurrencyAmount = CurrencyAmount - ?
                WHERE UserId = ? AND CurrencyAmount >= ?
            """, (amount, user_id, amount))
            
            if cursor.rowcount == 0:
                # Update failed - insufficient funds or user doesn't exist
                # Check if user exists but has no money, or doesn't exist
                check = await db.execute("SELECT 1 FROM DiscordUser WHERE UserId = ?", (user_id,))
                if not await check.fetchone():
                    # Create user if doesn't exist (starts with 0, so still fails check)
                    await db.execute("INSERT OR IGNORE INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, 0)", (user_id,))
                return False
            
            # Log transaction
            await db.execute("""
                INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (user_id, -amount, transaction_type, extra, other_id, note))
            
            await db.commit()
            return True

    # Bank methods
    async def get_bank_balance(self, user_id: int) -> int:
        """Get user's bank balance"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT Balance FROM BankUsers WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def deposit_bank(self, user_id: int, amount: int) -> bool:
        """Deposit currency to bank"""
        async with self.db._get_connection() as db:
            
            # Atomic deduct from wallet
            cursor = await db.execute("""
                UPDATE DiscordUser
                SET CurrencyAmount = CurrencyAmount - ?
                WHERE UserId = ? AND CurrencyAmount >= ?
            """, (amount, user_id, amount))
            
            if cursor.rowcount == 0:
                return False
            
            # Add to bank
            await db.execute("""
                INSERT INTO BankUsers (UserId, Balance) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET Balance = Balance + ?
            """, (user_id, amount, amount))
            
            # Log transaction
            await db.execute("""
                INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, Reason, DateAdded)
                VALUES (?, ?, 'bank_deposit', 'bank', ?, datetime('now'))
            """, (user_id, -amount, f"Deposited {amount} to bank"))
            
            await db.commit()
            return True
    
    async def withdraw_bank(self, user_id: int, amount: int) -> bool:
        """Withdraw currency from bank"""
        async with self.db._get_connection() as db:
            
            # Atomic deduct from bank
            cursor = await db.execute("""
                UPDATE BankUsers
                SET Balance = Balance - ?
                WHERE UserId = ? AND Balance >= ?
            """, (amount, user_id, amount))
            
            if cursor.rowcount == 0:
                return False
            
            # Add to wallet
            await db.execute("""
                INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
            """, (user_id, amount, amount))
            
            # Log transaction
            await db.execute("""
                INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, Reason, DateAdded)
                VALUES (?, ?, 'bank_withdraw', 'bank', ?, datetime('now'))
            """, (user_id, amount, f"Withdrew {amount} from bank"))
            
            await db.commit()
            return True

    async def get_bank_user(self, user_id: int):
        """Get or create bank user"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Balance, InterestRate FROM BankUsers WHERE UserId = ?
            """, (user_id,))
            result = await cursor.fetchone()
            
            if not result:
                await db.execute("""
                    INSERT INTO BankUsers (UserId, Balance, InterestRate) VALUES (?, 0, 0.02)
                """, (user_id,))
                await db.commit()
                return (0, 0.02)
            
            return result

    async def update_bank_balance(self, user_id: int, new_balance: int):
        """Update bank balance"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT OR REPLACE INTO BankUsers (UserId, Balance, InterestRate)
                VALUES (?, ?, COALESCE((SELECT InterestRate FROM BankUsers WHERE UserId = ?), 0.02))
            """, (user_id, new_balance, user_id))
            await db.commit()

    # Timely methods
    async def check_timely_cooldown(self, user_id: int, cooldown_hours: int) -> bool:
        """Check if user can claim timely reward"""
        cooldown_seconds = cooldown_hours * 3600
        
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT LastClaim FROM TimelyCooldown WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            
            if not row:
                return True
            
            last_claim = datetime.fromisoformat(row[0])
            return (datetime.now() - last_claim).total_seconds() >= cooldown_seconds
    
    async def claim_timely(self, user_id: int, amount: int, cooldown_hours: int) -> bool:
        """Claim timely reward"""
        if not await self.check_timely_cooldown(user_id, cooldown_hours):
            return False
        
        await self.add_currency(user_id, amount, "timely", "daily", note="Daily timely reward")
        
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT INTO TimelyCooldown (UserId, LastClaim) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET LastClaim = ?
            """, (user_id, datetime.now().isoformat(), datetime.now().isoformat()))
            await db.commit()
        
        return True

    async def get_timely_info(self, user_id: int):
        """Get timely cooldown info"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT LastClaim, Streak FROM TimelyCooldown WHERE UserId = ?
            """, (user_id,))
            result = await cursor.fetchone()
            
            if not result:
                return None, 0
            
            return result

    async def update_timely_claim(self, user_id: int, streak: int):
        """Update timely claim info"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT OR REPLACE INTO TimelyCooldown (UserId, LastClaim, Streak) 
                VALUES (?, datetime('now'), ?)
            """, (user_id, streak))
            await db.commit()

    # Leaderboard methods
    async def get_top_currency_users(self, limit: int = 10, offset: int = 0):
        """Get top currency users globally"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT UserId, CurrencyAmount FROM DiscordUser 
                ORDER BY CurrencyAmount DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            return await cursor.fetchall()

    # Currency Transaction Methods
    async def log_currency_transaction(self, user_id: int, transaction_type: str, amount: int, reason: str = None, other_id: int = None, extra: str = None):
        """Log a currency transaction"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT INTO CurrencyTransactions (UserId, Type, Amount, Reason, OtherId, Extra, DateAdded)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """, (user_id, transaction_type, amount, reason, other_id, extra))
            await db.commit()

    async def get_currency_transactions(self, user_id: int, limit: int = 50):
        """Get recent currency transactions for a user"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Type, Amount, Reason, DateAdded FROM CurrencyTransactions
                WHERE UserId = ? ORDER BY DateAdded DESC LIMIT ?
            """, (user_id, limit))
            return await cursor.fetchall()

    # Gambling Stats Methods
    async def update_gambling_stats(self, feature: str, bet_amount: int, win_amount: int, loss_amount: int):
        """Update global gambling statistics"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT OR REPLACE INTO GamblingStats (Feature, BetAmount, WinAmount, LossAmount)
                VALUES (?, 
                    COALESCE((SELECT BetAmount FROM GamblingStats WHERE Feature = ?), 0) + ?,
                    COALESCE((SELECT WinAmount FROM GamblingStats WHERE Feature = ?), 0) + ?,
                    COALESCE((SELECT LossAmount FROM GamblingStats WHERE Feature = ?), 0) + ?)
            """, (feature, feature, bet_amount, feature, win_amount, feature, loss_amount))
            await db.commit()

    async def update_user_bet_stats(self, user_id: int, game: str, bet_amount: int, win_amount: int, loss_amount: int, current_win: int = 0):
        """Update user betting statistics"""
        async with self.db._get_connection() as db:
            
            # Get current max win
            cursor = await db.execute("""
                SELECT MaxWin FROM UserBetStats WHERE UserId = ? AND Game = ?
            """, (user_id, game))
            result = await cursor.fetchone()
            max_win = max(result[0] if result else 0, current_win)
            
            await db.execute("""
                INSERT OR REPLACE INTO UserBetStats (UserId, Game, BetAmount, WinAmount, LossAmount, MaxWin)
                VALUES (?, ?, 
                    COALESCE((SELECT BetAmount FROM UserBetStats WHERE UserId = ? AND Game = ?), 0) + ?,
                    COALESCE((SELECT WinAmount FROM UserBetStats WHERE UserId = ? AND Game = ?), 0) + ?,
                    COALESCE((SELECT LossAmount FROM UserBetStats WHERE UserId = ? AND Game = ?), 0) + ?,
                    ?)
            """, (user_id, game, user_id, game, bet_amount, user_id, game, win_amount, user_id, game, loss_amount, max_win))
            await db.commit()

    async def get_user_bet_stats(self, user_id: int):
        """Get user betting statistics"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Game, BetAmount, WinAmount, LossAmount, MaxWin FROM UserBetStats 
                WHERE UserId = ? ORDER BY BetAmount DESC
            """, (user_id,))
            return await cursor.fetchall()

    # Rakeback Methods
    async def get_rakeback_balance(self, user_id: int):
        """Get user's rakeback balance"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT RakebackBalance FROM Rakeback WHERE UserId = ?
            """, (user_id,))
            result = await cursor.fetchone()
            return result[0] if result else 0

    async def add_rakeback(self, user_id: int, amount: int):
        """Add to user's rakeback balance"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT OR REPLACE INTO Rakeback (UserId, RakebackBalance) 
                VALUES (?, COALESCE((SELECT RakebackBalance FROM Rakeback WHERE UserId = ?), 0) + ?)
            """, (user_id, user_id, amount))
            await db.commit()

    async def claim_rakeback(self, user_id: int):
        """Claim and reset rakeback balance"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT RakebackBalance FROM Rakeback WHERE UserId = ?
            """, (user_id,))
            result = await cursor.fetchone()
            balance = result[0] if result else 0
            
            if balance > 0:
                await db.execute("""
                    UPDATE Rakeback SET RakebackBalance = 0 WHERE UserId = ?
                """, (user_id,))
                await db.commit()
            
            return balance

    # Currency generation channel methods
    async def get_currency_generation_channels(self, guild_id: int = None):
        """Get currency generation channels"""
        async with self.db._get_connection() as db:
            if guild_id:
                cursor = await db.execute("""
                    SELECT Id, GuildId, ChannelId FROM GCChannelId WHERE GuildId = ?
                """, (guild_id,))
            else:
                cursor = await db.execute("""
                    SELECT Id, GuildId, ChannelId FROM GCChannelId
                """)
            return await cursor.fetchall()
    
    async def add_currency_generation_channel(self, guild_id: int, channel_id: int):
        """Add a channel for currency generation"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT OR REPLACE INTO GCChannelId (GuildId, ChannelId) VALUES (?, ?)
            """, (guild_id, channel_id))
            await db.commit()
    
    async def remove_currency_generation_channel(self, guild_id: int, channel_id: int):
        """Remove a channel from currency generation"""
        async with self.db._get_connection() as db:
            await db.execute("""
                DELETE FROM GCChannelId WHERE GuildId = ? AND ChannelId = ?
            """, (guild_id, channel_id))
            await db.commit()
