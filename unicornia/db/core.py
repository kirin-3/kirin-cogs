"""
Core Database Logic
"""

import aiosqlite
import math
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
from contextlib import asynccontextmanager

log = logging.getLogger("red.unicornia.database")


@dataclass
class LevelStats:
    """Represents a user's level statistics"""
    level: int
    level_xp: int
    required_xp: int
    total_xp: int


class CoreDB:
    """Core database functionality"""
    
    def __init__(self, db_path: str, nadeko_db_path: str = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.nadeko_db_path = nadeko_db_path
        self._conn = None

    async def connect(self):
        """Establish a persistent database connection"""
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            # Set up WAL mode immediately on connection
            await self._setup_wal_mode(self._conn)
            log.info(f"Connected to database at {self.db_path}")

    async def close(self):
        """Close the persistent database connection"""
        if self._conn:
            await self._conn.close()
            self._conn = None
            log.info("Closed database connection")
    
    @asynccontextmanager
    async def _get_connection(self):
        """Yield the persistent database connection"""
        if self._conn is None:
            await self.connect()
        yield self._conn
    
    async def _setup_wal_mode(self, db):
        """Set up WAL mode and optimizations for a database connection"""
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA cache_size=1000")
        await db.execute("PRAGMA temp_store=MEMORY")
        await db.execute("PRAGMA mmap_size=33554432")  # 32MB memory mapping (Safe for 1GB VPS)
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
                # Using PASSIVE to avoid locking the database
                await db.execute("PRAGMA wal_checkpoint(PASSIVE)")
                
                return True
        except Exception as e:
            log.error(f"WAL integrity check failed: {e}")
            return False
    
    async def initialize(self):
        """Initialize the database with all required tables"""
        async with self._get_connection() as db:
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
            
            # Currency Transaction table (matching Nadeko's CurrencyTransaction)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS CurrencyTransaction (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                UserId INTEGER NOT NULL,
                Type TEXT NOT NULL,
                Amount INTEGER NOT NULL,
                Reason TEXT,
                OtherId INTEGER,
                Extra TEXT,
                DateAdded TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)
            
            # Bank User table (matching Nadeko's BankUser)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS BankUser (
                UserId INTEGER PRIMARY KEY,
                Balance INTEGER NOT NULL DEFAULT 0,
                InterestRate REAL NOT NULL DEFAULT 0.02
            )
            """)
            
            # Gambling Stats table (matching Nadeko's GamblingStats)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS GamblingStats (
                Feature TEXT PRIMARY KEY,
                BetAmount INTEGER NOT NULL DEFAULT 0,
                WinAmount INTEGER NOT NULL DEFAULT 0,
                LossAmount INTEGER NOT NULL DEFAULT 0
            )
            """)
            
            # User Bet Stats table (matching Nadeko's UserBetStats)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS UserBetStats (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                UserId INTEGER NOT NULL,
                Game TEXT NOT NULL,
                BetAmount INTEGER NOT NULL DEFAULT 0,
                WinAmount INTEGER NOT NULL DEFAULT 0,
                LossAmount INTEGER NOT NULL DEFAULT 0,
                MaxWin INTEGER NOT NULL DEFAULT 0,
                UNIQUE(UserId, Game)
            )
            """)
            
            # XP Excluded Item table (matching Nadeko's XpExcludedItem)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS XpExcludedItem (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                GuildId INTEGER NOT NULL,
                ItemId INTEGER NOT NULL,
                ItemType INTEGER NOT NULL
            )
            """)
            
            # XP Settings table (matching Nadeko's XpSettings)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS XpSettings (
                GuildId INTEGER PRIMARY KEY,
                XpRateMultiplier REAL NOT NULL DEFAULT 1.0,
                XpPerMessage INTEGER NOT NULL DEFAULT 3,
                XpMinutesTimeout INTEGER NOT NULL DEFAULT 5
            )
            """)
            
            # XP Role Reward table (matching Nadeko's XpRoleReward)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS XpRoleReward (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                GuildId INTEGER NOT NULL,
                Level INTEGER NOT NULL,
                RoleId INTEGER NOT NULL,
                Remove BOOLEAN NOT NULL DEFAULT FALSE
            )
            """)

            # Club Info table (matching Nadeko's ClubInfo)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS ClubInfo (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                Name TEXT NOT NULL,
                Description TEXT,
                ImageUrl TEXT DEFAULT '',
                BannerUrl TEXT DEFAULT '',
                Xp INTEGER DEFAULT 0,
                OwnerId INTEGER,
                DateAdded TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(Name)
            )
            """)

            # Club Applicants table (matching Nadeko's ClubApplicants)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS ClubApplicants (
                ClubId INTEGER,
                UserId INTEGER,
                DateAdded TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ClubId, UserId),
                FOREIGN KEY (ClubId) REFERENCES ClubInfo(Id) ON DELETE CASCADE
            )
            """)

            # Club Bans table (matching Nadeko's ClubBans)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS ClubBans (
                ClubId INTEGER,
                UserId INTEGER,
                DateAdded TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ClubId, UserId),
                FOREIGN KEY (ClubId) REFERENCES ClubInfo(Id) ON DELETE CASCADE
            )
            """)
            
            # Event table for currency events (matching Nadeko's Event)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS Event (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                GuildId INTEGER NOT NULL,
                ChannelId INTEGER NOT NULL,
                Event TEXT NOT NULL
            )
            """)
            
            # Rakeback table (matching Nadeko's Rakeback)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS Rakeback (
                UserId INTEGER PRIMARY KEY,
                RakebackBalance INTEGER NOT NULL DEFAULT 0
            )
            """)
            
            # Timely Cooldown table for daily/timely rewards
            await db.execute("""
            CREATE TABLE IF NOT EXISTS TimelyCooldown (
                UserId INTEGER PRIMARY KEY,
                LastClaim TEXT NOT NULL,
                Streak INTEGER NOT NULL DEFAULT 0
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
            
            # Create Indices for Performance
            await db.execute("CREATE INDEX IF NOT EXISTS idx_xp_guild_xp ON UserXpStats(GuildId, Xp DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_currency_amount ON DiscordUser(CurrencyAmount DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON currency_transactions(user_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_club_xp ON ClubInfo(Xp DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_club ON DiscordUser(ClubId)")
            
            await db.commit()
            
            # Run schema updates for existing databases
            await self._update_database_schema(db)
    
    async def _update_database_schema(self, db):
        """Update existing database schema to add missing columns"""
        try:
            # Check if IsUsing column exists in XpShopOwnedItem table
            cursor = await db.execute("PRAGMA table_info(XpShopOwnedItem)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]  # Column name is at index 1
            
            if 'IsUsing' not in column_names:
                log.info("Adding IsUsing column to XpShopOwnedItem table")
                await db.execute("ALTER TABLE XpShopOwnedItem ADD COLUMN IsUsing BOOLEAN DEFAULT FALSE")
                await db.commit()
                log.info("Successfully added IsUsing column")
                
        except Exception as e:
            log.error(f"Error updating database schema: {e}")
            
    # Level calculation methods (using Nadeko's exact formula)
    @staticmethod
    def calculate_level_stats(total_xp: int) -> LevelStats:
        """Calculate level statistics from total XP (using Nadeko's formula)"""
        if total_xp < 0:
            total_xp = 0

        level = CoreDB.get_level_by_total_xp(total_xp)
        xp_for_current_level = CoreDB.get_total_xp_req_for_level(level)
        level_xp = total_xp - xp_for_current_level
        required_xp = CoreDB.get_required_xp_for_next_level(level)

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

    # Data deletion methods for Red bot compliance
    async def delete_user_data(self, user_id: int):
        """Delete all data for a user (Red bot requirement)"""
        async with self._get_connection() as db:
            
            # Delete from all user-related tables
            tables_to_clean = [
                "UserXpStats",
                "CurrencyTransaction", 
                "BankUser",
                "TimelyCooldown",
                "waifus",  # Remove waifu claims
                "waifu_updates",  # Remove waifu history
                "XpShopOwnedItem"
            ]
            
            for table in tables_to_clean:
                try:
                    await db.execute(f"DELETE FROM {table} WHERE UserId = ?", (user_id,))
                except Exception as e:
                    # Some tables might not exist or have different column names
                    log.warning(f"Could not clean table {table} for user {user_id}: {e}")
            
            # Clean waifu tables with different column names
            try:
                await db.execute("DELETE FROM waifus WHERE claimer_id = ?", (user_id,))
            except Exception:
                pass
                
            try:
                await db.execute("DELETE FROM waifu_updates WHERE old_claimer_id = ? OR new_claimer_id = ?", (user_id, user_id))
            except Exception:
                pass
            
            await db.commit()
            log.info(f"Deleted all data for user {user_id}")
