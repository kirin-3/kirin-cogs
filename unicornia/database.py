"""
Database models and operations for Unicornia
"""

import aiosqlite
import math
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("red.unicornia.database")


@dataclass
class LevelStats:
    """Represents a user's level statistics"""
    level: int
    level_xp: int
    required_xp: int
    total_xp: int


class DatabaseManager:
    """Handles all database operations for Unicornia"""
    
    def __init__(self, db_path: str, nadeko_db_path: str = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.nadeko_db_path = nadeko_db_path
    
    def _get_connection(self):
        """Get a database connection with WAL mode enabled"""
        return aiosqlite.connect(self.db_path)
    
    async def _setup_wal_mode(self, db):
        """Set up WAL mode and optimizations for a database connection"""
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA cache_size=1000")
        await db.execute("PRAGMA temp_store=MEMORY")
        await db.execute("PRAGMA mmap_size=268435456")  # 256MB memory mapping
        await db.execute("PRAGMA page_size=4096")  # 4KB page size
        await db.execute("PRAGMA auto_vacuum=INCREMENTAL")  # Incremental vacuum
    
    async def check_wal_integrity(self) -> bool:
        """Check WAL mode integrity and perform maintenance if needed"""
        try:
            async with self._get_connection() as db:
                # Set up WAL mode and optimizations
                await self._setup_wal_mode(db)
                
                # Check if WAL mode is active
                cursor = await db.execute("PRAGMA journal_mode")
                mode = await cursor.fetchone()
                if mode[0] != "wal":
                    log.warning("Database not in WAL mode, attempting to enable...")
                    await db.execute("PRAGMA journal_mode=WAL")
                    await db.commit()
                
                # Check database integrity
                cursor = await db.execute("PRAGMA integrity_check")
                result = await cursor.fetchone()
                if result[0] != "ok":
                    log.error(f"Database integrity check failed: {result[0]}")
                    return False
                
                # Perform WAL checkpoint to prevent WAL file from growing too large
                await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                
                return True
        except Exception as e:
            log.error(f"WAL integrity check failed: {e}")
            return False
    
    async def initialize(self):
        """Initialize the database with all required tables"""
        async with self._get_connection() as db:
            # Set up WAL mode and optimizations
            await self._setup_wal_mode(db)
            # Create tables matching Nadeko's structure
            await db.execute("""
                CREATE TABLE IF NOT EXISTS DiscordUser (
                    UserId INTEGER PRIMARY KEY,
                    Username TEXT,
                    AvatarId TEXT,
                    ClubId INTEGER,
                    IsClubAdmin INTEGER DEFAULT 0,
                    TotalXp INTEGER DEFAULT 0,
                    CurrencyAmount INTEGER DEFAULT 0
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS UserXpStats (
                    UserId INTEGER,
                    GuildId INTEGER,
                    Xp INTEGER DEFAULT 0,
                    PRIMARY KEY (UserId, GuildId)
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS BankUsers (
                    UserId INTEGER PRIMARY KEY,
                    Balance INTEGER DEFAULT 0
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
                CREATE TABLE IF NOT EXISTS PlantedCurrency (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT,
                    GuildId INTEGER,
                    ChannelId INTEGER,
                    UserId INTEGER,
                    MessageId INTEGER,
                    Amount INTEGER,
                    Password TEXT
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
            
        # XP Shop Owned Items table (matching Nadeko's XpShopOwnedItem)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS XpShopOwnedItem (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                UserId INTEGER,
                ItemType INTEGER,
                ItemKey TEXT,
                IsUsing BOOLEAN DEFAULT FALSE,
                UNIQUE(UserId, ItemType, ItemKey)
            )
        """)
        
        # Shop system tables (matching Nadeko structure)
        await db.execute("""
                CREATE TABLE IF NOT EXISTS ShopEntry (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT,
                    GuildId INTEGER,
                    `Index` INTEGER,
                    Price INTEGER,
                    Name TEXT,
                    AuthorId INTEGER,
                    Type INTEGER,
                    RoleName TEXT,
                    RoleId INTEGER,
                    RoleRequirement INTEGER,
                    Command TEXT
                )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ShopEntryItem (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ShopEntryId INTEGER,
                    Text TEXT,
                    FOREIGN KEY (ShopEntryId) REFERENCES ShopEntry(Id) ON DELETE CASCADE
                )
        """)
        
        # XP Currency Rewards table
        await db.execute("""
                CREATE TABLE IF NOT EXISTS XpCurrencyReward (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT,
                    XpSettingsId INTEGER,
                    Level INTEGER,
                    Amount INTEGER
                )
        """)
        
        # Currency Generation Channels table
        await db.execute("""
                CREATE TABLE IF NOT EXISTS GCChannelId (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT,
                    GuildId INTEGER,
                    ChannelId INTEGER,
                    UNIQUE(GuildId, ChannelId)
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
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("SELECT CurrencyAmount FROM DiscordUser WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def add_currency(self, user_id: int, amount: int, transaction_type: str, extra: str = "", other_id: int = None, note: str = ""):
        """Add currency to user's wallet"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            # Update user currency
            await db.execute("""
                INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
            """, (user_id, amount, amount))
            
            # Log transaction
            await db.execute("""
                INSERT INTO currency_transactions (user_id, amount, type, extra, other_id, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, amount, transaction_type, extra, other_id, note))
            
            await db.commit()
    
    async def remove_currency(self, user_id: int, amount: int, transaction_type: str, extra: str = "", other_id: int = None, note: str = "") -> bool:
        """Remove currency from user's wallet"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            # Check if user has enough currency
            cursor = await db.execute("SELECT CurrencyAmount FROM DiscordUser WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            current_balance = row[0] if row else 0
            
            if current_balance < amount:
                return False
            
            # Update user currency
            await db.execute("""
                INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount - ?
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
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("SELECT Xp FROM UserXpStats WHERE UserId = ? AND GuildId = ?", (user_id, guild_id))
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def add_xp(self, user_id: int, guild_id: int, amount: int):
        """Add XP to user in a guild"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            await db.execute("""
                INSERT INTO UserXpStats (UserId, GuildId, Xp) VALUES (?, ?, ?)
                ON CONFLICT(UserId, GuildId) DO UPDATE SET Xp = Xp + ?
            """, (user_id, guild_id, amount, amount))
            
            # Update total XP
            await db.execute("""
                INSERT INTO DiscordUser (UserId, TotalXp) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET TotalXp = TotalXp + ?
            """, (user_id, amount, amount))
            
            await db.commit()
    
    # Bank methods
    async def get_bank_balance(self, user_id: int) -> int:
        """Get user's bank balance"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("SELECT Balance FROM BankUsers WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            return row[0] if row else 0
    
    async def deposit_bank(self, user_id: int, amount: int) -> bool:
        """Deposit currency to bank"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            # Check if user has enough currency
            cursor = await db.execute("SELECT CurrencyAmount FROM DiscordUser WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            current_balance = row[0] if row else 0
            
            if current_balance < amount:
                return False
            
            # Remove from wallet
            await db.execute("""
                INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount - ?
            """, (user_id, -amount, amount))
            
            # Add to bank
            await db.execute("""
                INSERT INTO BankUsers (UserId, Balance) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET Balance = Balance + ?
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
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            # Check if user has enough in bank
            cursor = await db.execute("SELECT Balance FROM BankUsers WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            bank_balance = row[0] if row else 0
            
            if bank_balance < amount:
                return False
            
            # Remove from bank
            await db.execute("""
                INSERT INTO BankUsers (UserId, Balance) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET Balance = Balance - ?
            """, (user_id, -amount, amount))
            
            # Add to wallet
            await db.execute("""
                INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
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
        
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
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
        
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            await db.execute("""
                INSERT INTO timely_claims (user_id, last_claim) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET last_claim = ?
            """, (user_id, datetime.now().isoformat(), datetime.now().isoformat()))
            await db.commit()
        
        return True
    
    # Leaderboard methods
    async def get_top_xp_users(self, guild_id: int, limit: int = 10, offset: int = 0):
        """Get top XP users in a guild"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("""
                SELECT UserId, Xp FROM UserXpStats 
                WHERE GuildId = ? 
                ORDER BY Xp DESC 
                LIMIT ? OFFSET ?
            """, (guild_id, limit, offset))
            return await cursor.fetchall()
    
    async def get_top_currency_users(self, limit: int = 10, offset: int = 0):
        """Get top currency users globally"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("""
                SELECT UserId, CurrencyAmount FROM DiscordUser 
                ORDER BY CurrencyAmount DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            return await cursor.fetchall()
    
    async def migrate_from_nadeko(self):
        """Migrate data from existing Nadeko database"""
        # Try multiple possible paths for Nadeko database
        possible_paths = [
            self.nadeko_db_path,
            "/data/nadeko.db",
            "data/nadeko.db",
            "nadeko.db",
            "data/nadeko/nadeko.db"
        ]
        
        nadeko_db_path = None
        for path in possible_paths:
            if path and Path(path).exists():
                nadeko_db_path = path
                break
        
        if not nadeko_db_path:
            log.info("No Nadeko database found in any of the expected locations, skipping migration")
            log.info(f"Searched paths: {possible_paths}")
            return
        
        log.info(f"Starting migration from Nadeko database at {nadeko_db_path}...")
        
        try:
            async with aiosqlite.connect(nadeko_db_path) as nadeko_db:
                # Check database size first
                cursor = await nadeko_db.execute("SELECT COUNT(*) FROM DiscordUser")
                user_count = (await cursor.fetchone())[0]
                log.info(f"Found {user_count} users to migrate from DiscordUser table")
                
                # Migrate DiscordUser data with batch processing
                migrated_users = 0
                batch_size = 1000
                batch_data = []
                
                async with nadeko_db.execute("SELECT UserId, Username, AvatarId, TotalXp, CurrencyAmount FROM DiscordUser") as cursor:
                    async for row in cursor:
                        user_id, username, avatar_id, total_xp, currency_amount = row
                        batch_data.append((user_id, username, avatar_id, total_xp, currency_amount))
                        migrated_users += 1
                        
                        # Process batch when it reaches batch_size
                        if len(batch_data) >= batch_size:
                            async with self._get_connection() as db:
                                await self._setup_wal_mode(db)
                                await db.executemany("""
                                    INSERT OR REPLACE INTO DiscordUser (UserId, Username, AvatarId, TotalXp, CurrencyAmount)
                                    VALUES (?, ?, ?, ?, ?)
                                """, batch_data)
                                await db.commit()
                            log.info(f"Migrated {migrated_users}/{user_count} users...")
                            batch_data.clear()
                
                # Process remaining batch
                if batch_data:
                    async with self._get_connection() as db:
                        await self._setup_wal_mode(db)
                        await db.executemany("""
                            INSERT OR REPLACE INTO DiscordUser (UserId, Username, AvatarId, TotalXp, CurrencyAmount)
                            VALUES (?, ?, ?, ?, ?)
                        """, batch_data)
                        await db.commit()
                
                log.info(f"Completed DiscordUser migration: {migrated_users} users")
                
                # Migrate UserXpStats data
                cursor = await nadeko_db.execute("SELECT COUNT(*) FROM UserXpStats")
                xp_count = (await cursor.fetchone())[0]
                log.info(f"Found {xp_count} XP stats to migrate from UserXpStats table")
                
                migrated_xp = 0
                batch_data = []
                
                async with nadeko_db.execute("SELECT UserId, GuildId, Xp FROM UserXpStats") as cursor:
                    async for row in cursor:
                        user_id, guild_id, xp = row
                        batch_data.append((user_id, guild_id, xp))
                        migrated_xp += 1
                        
                        # Process batch when it reaches batch_size
                        if len(batch_data) >= batch_size:
                            async with self._get_connection() as db:
                                await self._setup_wal_mode(db)
                                await db.executemany("""
                                    INSERT OR REPLACE INTO UserXpStats (UserId, GuildId, Xp)
                                    VALUES (?, ?, ?)
                                """, batch_data)
                                await db.commit()
                            log.info(f"Migrated {migrated_xp}/{xp_count} XP stats...")
                            batch_data.clear()
                
                # Process remaining batch
                if batch_data:
                    async with self._get_connection() as db:
                        await self._setup_wal_mode(db)
                        await db.executemany("""
                            INSERT OR REPLACE INTO UserXpStats (UserId, GuildId, Xp)
                            VALUES (?, ?, ?)
                        """, batch_data)
                        await db.commit()
                
                log.info(f"Completed UserXpStats migration: {migrated_xp} entries")
                
                # Migrate BankUsers data
                async with nadeko_db.execute("SELECT UserId, Balance FROM BankUsers") as cursor:
                    async for row in cursor:
                        user_id, balance = row
                        async with self._get_connection() as db:
                            await self._setup_wal_mode(db)
                            await db.execute("""
                                INSERT OR REPLACE INTO BankUsers (UserId, Balance)
                                VALUES (?, ?)
                            """, (user_id, balance))
                            await db.commit()
                
                # Migrate PlantedCurrency data
                async with nadeko_db.execute("SELECT GuildId, ChannelId, UserId, MessageId, Amount, Password FROM PlantedCurrency") as cursor:
                    async for row in cursor:
                        guild_id, channel_id, user_id, message_id, amount, password = row
                        async with self._get_connection() as db:
                            await self._setup_wal_mode(db)
                            await db.execute("""
                                INSERT OR REPLACE INTO PlantedCurrency (GuildId, ChannelId, UserId, MessageId, Amount, Password)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (guild_id, channel_id, user_id, message_id, amount, password))
                            await db.commit()
                
                # Migrate ShopEntry data (if exists)
                try:
                    async with nadeko_db.execute("SELECT Id, GuildId, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command FROM ShopEntry") as cursor:
                        async for row in cursor:
                            entry_id, guild_id, index, price, name, author_id, entry_type, role_name, role_id, role_requirement, command = row
                            async with self._get_connection() as db:
                                await self._setup_wal_mode(db)
                                await db.execute("""
                                    INSERT OR REPLACE INTO ShopEntry (Id, GuildId, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (entry_id, guild_id, index, price, name, author_id, entry_type, role_name, role_id, role_requirement, command))
                                await db.commit()
                except Exception as e:
                    log.info(f"ShopEntry table not found or empty: {e}")
                
                # Migrate ShopEntryItem data (if exists)
                try:
                    async with nadeko_db.execute("SELECT Id, ShopEntryId, Text FROM ShopEntryItem") as cursor:
                        async for row in cursor:
                            item_id, shop_entry_id, text = row
                            async with self._get_connection() as db:
                                await self._setup_wal_mode(db)
                                await db.execute("""
                                    INSERT OR REPLACE INTO ShopEntryItem (Id, ShopEntryId, Text)
                                    VALUES (?, ?, ?)
                                """, (item_id, shop_entry_id, text))
                                await db.commit()
                except Exception as e:
                    log.info(f"ShopEntryItem table not found or empty: {e}")
                
                # Migrate XpCurrencyReward data (if exists)
                try:
                    async with nadeko_db.execute("SELECT Id, XpSettingsId, Level, Amount FROM XpCurrencyReward") as cursor:
                        async for row in cursor:
                            reward_id, xp_settings_id, level, amount = row
                            async with self._get_connection() as db:
                                await self._setup_wal_mode(db)
                                await db.execute("""
                                    INSERT OR REPLACE INTO XpCurrencyReward (Id, XpSettingsId, Level, Amount)
                                    VALUES (?, ?, ?, ?)
                                """, (reward_id, xp_settings_id, level, amount))
                                await db.commit()
                except Exception as e:
                    log.info(f"XpCurrencyReward table not found or empty: {e}")
                
                # Migrate GCChannelId data (if exists)
                try:
                    async with nadeko_db.execute("SELECT Id, GuildId, ChannelId FROM GCChannelId") as cursor:
                        async for row in cursor:
                            gc_id, guild_id, channel_id = row
                            async with self._get_connection() as db:
                                await self._setup_wal_mode(db)
                                await db.execute("""
                                    INSERT OR REPLACE INTO GCChannelId (Id, GuildId, ChannelId)
                                    VALUES (?, ?, ?)
                                """, (gc_id, guild_id, channel_id))
                                await db.commit()
                except Exception as e:
                    log.info(f"GCChannelId table not found or empty: {e}")
                
                log.info("Migration from Nadeko database completed successfully")
                
        except Exception as e:
            log.error(f"Error during migration from Nadeko database: {e}")
            raise
    
    # Shop system methods
    async def get_shop_entries(self, guild_id: int):
        """Get all shop entries for a guild"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("""
                SELECT Id, GuildId, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command
                FROM ShopEntry WHERE GuildId = ? ORDER BY `Index`
            """, (guild_id,))
            return await cursor.fetchall()
    
    async def get_shop_entry_items(self, shop_entry_id: int):
        """Get items for a shop entry"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("""
                SELECT Id, Text FROM ShopEntryItem WHERE ShopEntryId = ?
            """, (shop_entry_id,))
            return await cursor.fetchall()
    
    async def add_shop_entry(self, guild_id: int, index: int, price: int, name: str, author_id: int, 
                           entry_type: int, role_name: str = None, role_id: int = None, 
                           role_requirement: int = None, command: str = None):
        """Add a new shop entry"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("""
                INSERT INTO ShopEntry (GuildId, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, index, price, name, author_id, entry_type, role_name, role_id, role_requirement, command))
            await db.commit()
            return cursor.lastrowid
    
    async def add_shop_entry_item(self, shop_entry_id: int, text: str):
        """Add an item to a shop entry"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            await db.execute("""
                INSERT INTO ShopEntryItem (ShopEntryId, Text) VALUES (?, ?)
            """, (shop_entry_id, text))
            await db.commit()
    
    # Currency generation channel methods
    async def get_currency_generation_channels(self, guild_id: int = None):
        """Get currency generation channels"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
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
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            await db.execute("""
                INSERT OR REPLACE INTO GCChannelId (GuildId, ChannelId) VALUES (?, ?)
            """, (guild_id, channel_id))
            await db.commit()
    
    async def remove_currency_generation_channel(self, guild_id: int, channel_id: int):
        """Remove a channel from currency generation"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            await db.execute("""
                DELETE FROM GCChannelId WHERE GuildId = ? AND ChannelId = ?
            """, (guild_id, channel_id))
            await db.commit()
    
    # XP currency reward methods
    async def get_xp_currency_rewards(self, xp_settings_id: int = None):
        """Get XP currency rewards"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            if xp_settings_id:
                cursor = await db.execute("""
                    SELECT Id, XpSettingsId, Level, Amount FROM XpCurrencyReward WHERE XpSettingsId = ?
                """, (xp_settings_id,))
            else:
                cursor = await db.execute("""
                    SELECT Id, XpSettingsId, Level, Amount FROM XpCurrencyReward
                """)
            return await cursor.fetchall()
    
    async def add_xp_currency_reward(self, xp_settings_id: int, level: int, amount: int):
        """Add an XP currency reward"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            await db.execute("""
                INSERT INTO XpCurrencyReward (XpSettingsId, Level, Amount) VALUES (?, ?, ?)
            """, (xp_settings_id, level, amount))
            await db.commit()
    
    # XP Shop methods
    async def get_user_xp_items(self, user_id: int, item_type: int = None):
        """Get user's owned XP shop items"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            
            # Ensure user has default background (free for everyone)
            if item_type == 1:  # Background type
                await self._ensure_default_background(user_id, db)
            
            if item_type is not None:
                cursor = await db.execute("""
                    SELECT Id, UserId, ItemType, ItemKey FROM XpShopOwnedItem 
                    WHERE UserId = ? AND ItemType = ?
                """, (user_id, item_type))
            else:
                cursor = await db.execute("""
                    SELECT Id, UserId, ItemType, ItemKey FROM XpShopOwnedItem 
                    WHERE UserId = ?
                """, (user_id,))
            return await cursor.fetchall()
    
    async def _ensure_default_background(self, user_id: int, db):
        """Ensure user has the default background and it's set as active if no other is active"""
        # Check if user already has default background
        cursor = await db.execute("""
            SELECT COUNT(*) FROM XpShopOwnedItem 
            WHERE UserId = ? AND ItemType = 1 AND ItemKey = 'default'
        """, (user_id,))
        count = (await cursor.fetchone())[0]
        
        if count == 0:
            # Check if user has any active background
            cursor = await db.execute("""
                SELECT COUNT(*) FROM XpShopOwnedItem 
                WHERE UserId = ? AND ItemType = 1 AND IsUsing = TRUE
            """, (user_id,))
            has_active = (await cursor.fetchone())[0] > 0
            
            # Give user the default background for free and set as active if no other is active
            await db.execute("""
                INSERT INTO XpShopOwnedItem (UserId, ItemType, ItemKey, IsUsing) VALUES (?, 1, 'default', ?)
            """, (user_id, not has_active))
            await db.commit()
    
    async def user_owns_xp_item(self, user_id: int, item_type: int, item_key: str) -> bool:
        """Check if user owns a specific XP shop item"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("""
                SELECT COUNT(*) FROM XpShopOwnedItem 
                WHERE UserId = ? AND ItemType = ? AND ItemKey = ?
            """, (user_id, item_type, item_key))
            count = (await cursor.fetchone())[0]
            return count > 0
    
    async def purchase_xp_item(self, user_id: int, item_type: int, item_key: str, price: int) -> bool:
        """Purchase an XP shop item"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            
            # Check if user already owns this item
            if await self.user_owns_xp_item(user_id, item_type, item_key):
                return False
            
            # Check if user has enough currency
            cursor = await db.execute("SELECT CurrencyAmount FROM DiscordUser WHERE UserId = ?", (user_id,))
            row = await cursor.fetchone()
            current_balance = row[0] if row else 0
            
            if current_balance < price:
                return False
            
            # Deduct currency
            await db.execute("""
                INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount - ?
            """, (user_id, -price, price))
            
            # Add item to user's collection
            await db.execute("""
                INSERT INTO XpShopOwnedItem (UserId, ItemType, ItemKey, IsUsing) VALUES (?, ?, ?, FALSE)
            """, (user_id, item_type, item_key))
            
            # Log transaction
            await db.execute("""
                INSERT INTO currency_transactions (user_id, amount, type, extra, note)
                VALUES (?, ?, 'xp_shop_purchase', ?, ?)
            """, (user_id, -price, item_key, f"Purchased XP item: {item_key}"))
            
            await db.commit()
            return True
    
    async def get_active_xp_item(self, user_id: int, item_type: int) -> str:
        """Get the user's active XP item of a given type"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            
            # Ensure user has default background
            if item_type == 1:  # Background type
                await self._ensure_default_background(user_id, db)
            
            cursor = await db.execute("""
                SELECT ItemKey FROM XpShopOwnedItem 
                WHERE UserId = ? AND ItemType = ? AND IsUsing = TRUE
            """, (user_id, item_type))
            result = await cursor.fetchone()
            
            if result:
                return result[0]
            
            # If no active item, return default
            return "default"
    
    async def set_active_xp_item(self, user_id: int, item_type: int, item_key: str) -> bool:
        """Set an XP item as active (user must own it first)"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            
            # Check if user owns the item
            if not await self.user_owns_xp_item(user_id, item_type, item_key):
                return False
            
            # Set all items of this type to not using
            await db.execute("""
                UPDATE XpShopOwnedItem 
                SET IsUsing = FALSE 
                WHERE UserId = ? AND ItemType = ?
            """, (user_id, item_type))
            
            # Set the specified item as using
            await db.execute("""
                UPDATE XpShopOwnedItem 
                SET IsUsing = TRUE 
                WHERE UserId = ? AND ItemType = ? AND ItemKey = ?
            """, (user_id, item_type, item_key))
            
            await db.commit()
            return True
    
    async def get_user_rank_in_guild(self, user_id: int, guild_id: int) -> int:
        """Get user's XP rank in a guild"""
        async with self._get_connection() as db:
            await self._setup_wal_mode(db)
            cursor = await db.execute("""
                SELECT COUNT(*) + 1 FROM UserXpStats 
                WHERE GuildId = ? AND Xp > (
                    SELECT COALESCE(Xp, 0) FROM UserXpStats 
                    WHERE UserId = ? AND GuildId = ?
                )
            """, (guild_id, user_id, guild_id))
            rank = (await cursor.fetchone())[0]
            return rank
