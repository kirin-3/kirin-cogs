"""
Database models and operations for Unicornia
"""

import aiosqlite
import math
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime


@dataclass
class LevelStats:
    """Represents a user's level statistics"""
    level: int
    level_xp: int
    required_xp: int
    total_xp: int


class DatabaseManager:
    """Handles all database operations for Unicornia"""
    
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    async def initialize(self):
        """Initialize the database with all required tables"""
        async with aiosqlite.connect(self.db_path) as db:
            # Create tables
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    currency_amount INTEGER DEFAULT 0,
                    total_xp INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_xp (
                    user_id INTEGER,
                    guild_id INTEGER,
                    xp INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id)
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bank_users (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS currency_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    type TEXT,
                    extra TEXT,
                    other_id INTEGER,
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS timely_claims (
                    user_id INTEGER PRIMARY KEY,
                    last_claim TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS shop_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    description TEXT,
                    price INTEGER,
                    item_type TEXT,
                    item_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_shop_items (
                    user_id INTEGER,
                    item_id INTEGER,
                    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, item_id)
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS waifus (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    waifu_id INTEGER,
                    claimer_id INTEGER,
                    price INTEGER DEFAULT 50,
                    affinity_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS waifu_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    waifu_id INTEGER,
                    name TEXT,
                    emoji TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS waifu_updates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    waifu_id INTEGER,
                    old_claimer_id INTEGER,
                    new_claimer_id INTEGER,
                    update_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS currency_plants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    guild_id INTEGER,
                    amount INTEGER,
                    password TEXT,
                    planted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS xp_shop_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    item_type TEXT,
                    item_key TEXT,
                    is_using BOOLEAN DEFAULT FALSE,
                    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.commit()
    
    # Level calculation methods (using Nadeko's exact formula)
    @staticmethod
    def calculate_level_stats(total_xp: int) -> LevelStats:
        """Calculate level statistics from total XP (using Nadeko's formula)"""
        if total_xp < 0:
            total_xp = 0

        level = DatabaseManager.get_level_by_total_xp(total_xp)
        xp_for_current_level = DatabaseManager.get_total_xp_req_for_level(level)
        level_xp = total_xp - xp_for_current_level
        required_xp = DatabaseManager.get_required_xp_for_next_level(level)

        return LevelStats(
            level=level,
            level_xp=level_xp,
            required_xp=required_xp,
            total_xp=total_xp
        )
    
    @staticmethod
    def get_level_by_total_xp(total_xp: int) -> int:
        """Get level from total XP (Nadeko's formula)"""
        if total_xp < 0:
            total_xp = 0
        return int((-7.0 / 2) + (1 / 6.0 * math.sqrt((8 * total_xp) + 441)))
    
    @staticmethod
    def get_total_xp_req_for_level(level: int) -> int:
        """Get total XP required for a specific level (Nadeko's formula)"""
        return ((9 * level * level) + (63 * level)) // 2
    
    @staticmethod
    def get_required_xp_for_next_level(level: int) -> int:
        """Get XP required for next level (Nadeko's formula)"""
        return (9 * (level + 1)) + 27
    
    # Currency methods
    async def get_user_currency(self, user_id: int) -> int:
        """Get user's wallet currency"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT currency_amount FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def add_currency(self, user_id: int, amount: int, transaction_type: str, extra: str = "", other_id: int = None, note: str = ""):
        """Add currency to user's wallet"""
        async with aiosqlite.connect(self.db_path) as db:
            # Update user currency
            await db.execute("""
                INSERT INTO users (user_id, currency_amount) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET currency_amount = currency_amount + ?
            """, (user_id, amount, amount))
            
            # Log transaction
            await db.execute("""
                INSERT INTO currency_transactions (user_id, amount, type, extra, other_id, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, amount, transaction_type, extra, other_id, note))
            
            await db.commit()
    
    async def remove_currency(self, user_id: int, amount: int, transaction_type: str, extra: str = "", other_id: int = None, note: str = "") -> bool:
        """Remove currency from user's wallet"""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if user has enough currency
            cursor = await db.execute("SELECT currency_amount FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            current_balance = row[0] if row else 0
            
            if current_balance < amount:
                return False
            
            # Update user currency
            await db.execute("""
                INSERT INTO users (user_id, currency_amount) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET currency_amount = currency_amount - ?
            """, (user_id, -amount, amount))
            
            # Log transaction
            await db.execute("""
                INSERT INTO currency_transactions (user_id, amount, type, extra, other_id, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, -amount, transaction_type, extra, other_id, note))
            
            await db.commit()
            return True
    
    # XP methods
    async def get_user_xp(self, user_id: int, guild_id: int) -> int:
        """Get user's XP in a guild"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT xp FROM user_xp WHERE user_id = ? AND guild_id = ?", (user_id, guild_id))
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def add_xp(self, user_id: int, guild_id: int, amount: int):
        """Add XP to user in a guild"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_xp (user_id, guild_id, xp) VALUES (?, ?, ?)
                ON CONFLICT(user_id, guild_id) DO UPDATE SET xp = xp + ?
            """, (user_id, guild_id, amount, amount))
            
            # Update total XP
            await db.execute("""
                INSERT INTO users (user_id, total_xp) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET total_xp = total_xp + ?
            """, (user_id, amount, amount))
            
            await db.commit()
    
    # Bank methods
    async def get_bank_balance(self, user_id: int) -> int:
        """Get user's bank balance"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT balance FROM bank_users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def deposit_bank(self, user_id: int, amount: int) -> bool:
        """Deposit currency to bank"""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if user has enough currency
            cursor = await db.execute("SELECT currency_amount FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            current_balance = row[0] if row else 0
            
            if current_balance < amount:
                return False
            
            # Remove from wallet
            await db.execute("""
                INSERT INTO users (user_id, currency_amount) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET currency_amount = currency_amount - ?
            """, (user_id, -amount, amount))
            
            # Add to bank
            await db.execute("""
                INSERT INTO bank_users (user_id, balance) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET balance = balance + ?
            """, (user_id, amount, amount))
            
            # Log transaction
            await db.execute("""
                INSERT INTO currency_transactions (user_id, amount, type, extra, note)
                VALUES (?, ?, 'bank_deposit', 'bank', ?)
            """, (user_id, -amount, f"Deposited {amount} to bank"))
            
            await db.commit()
            return True
    
    async def withdraw_bank(self, user_id: int, amount: int) -> bool:
        """Withdraw currency from bank"""
        async with aiosqlite.connect(self.db_path) as db:
            # Check if user has enough in bank
            cursor = await db.execute("SELECT balance FROM bank_users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            bank_balance = row[0] if row else 0
            
            if bank_balance < amount:
                return False
            
            # Remove from bank
            await db.execute("""
                INSERT INTO bank_users (user_id, balance) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET balance = balance - ?
            """, (user_id, -amount, amount))
            
            # Add to wallet
            await db.execute("""
                INSERT INTO users (user_id, currency_amount) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET currency_amount = currency_amount + ?
            """, (user_id, amount, amount))
            
            # Log transaction
            await db.execute("""
                INSERT INTO currency_transactions (user_id, amount, type, extra, note)
                VALUES (?, ?, 'bank_withdraw', 'bank', ?)
            """, (user_id, amount, f"Withdrew {amount} from bank"))
            
            await db.commit()
            return True
    
    # Timely methods
    async def check_timely_cooldown(self, user_id: int, cooldown_hours: int) -> bool:
        """Check if user can claim timely reward"""
        cooldown_seconds = cooldown_hours * 3600
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT last_claim FROM timely_claims WHERE user_id = ?", (user_id,))
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
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO timely_claims (user_id, last_claim) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET last_claim = ?
            """, (user_id, datetime.now().isoformat(), datetime.now().isoformat()))
            await db.commit()
        
        return True
    
    # Leaderboard methods
    async def get_top_xp_users(self, guild_id: int, limit: int = 10, offset: int = 0):
        """Get top XP users in a guild"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT user_id, xp FROM user_xp 
                WHERE guild_id = ? 
                ORDER BY xp DESC 
                LIMIT ? OFFSET ?
            """, (guild_id, limit, offset))
            return await cursor.fetchall()
    
    async def get_top_currency_users(self, limit: int = 10, offset: int = 0):
        """Get top currency users globally"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT user_id, currency_amount FROM users 
                ORDER BY currency_amount DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            return await cursor.fetchall()
