"""
Core Database Logic
"""

import aiosqlite
import math
import logging
import asyncio
from pathlib import Path
from typing import Optional
from datetime import datetime
from contextlib import asynccontextmanager

from ..types import LevelStats

log = logging.getLogger("red.unicornia.database")


class CoreDB:
    """Core database functionality"""
    
    def __init__(self, db_path: str, nadeko_db_path: str = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.nadeko_db_path = nadeko_db_path
        self._conn = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        """Establish a persistent database connection.
        
        Raises:
            sqlite3.Error: If connection fails.
        """
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            # Set up WAL mode immediately on connection
            await self._setup_wal_mode(self._conn)
            log.info(f"Connected to database at {self.db_path}")

    async def close(self) -> None:
        """Close the persistent database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            log.info("Closed database connection")
    
    @asynccontextmanager
    async def _get_connection(self):
        """Yield the persistent database connection"""
        async with self._lock:
            if self._conn is None:
                await self.connect()
            yield self._conn
    
    async def _setup_wal_mode(self, db: aiosqlite.Connection) -> None:
        """Set up WAL mode and optimizations for a database connection.
        
        Args:
            db: The database connection to configure.
        """
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA cache_size=-4000") # Negative value = pages in KiB (4000KB ~ 4MB) -> actually let's use pages. Positive = pages. 4000 pages * 4KB = 16MB.
        await db.execute("PRAGMA temp_store=MEMORY")
        await db.execute("PRAGMA mmap_size=33554432")  # 32MB memory mapping (Safe for 1GB VPS)
        await db.execute("PRAGMA page_size=4096")  # 4KB page size
        await db.execute("PRAGMA auto_vacuum=INCREMENTAL")  # Incremental vacuum
    
    async def check_wal_integrity(self) -> bool:
        """Check WAL mode integrity and perform maintenance if needed.
        
        Returns:
            bool: True if integrity check passed, False otherwise.
        """
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
    
    async def initialize(self) -> None:
        """Initialize the database with all required tables."""
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
            CREATE TABLE IF NOT EXISTS CurrencyTransactions (
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
            CREATE TABLE IF NOT EXISTS BankUsers (
                UserId INTEGER PRIMARY KEY,
                Balance INTEGER NOT NULL DEFAULT 0
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
            CREATE TABLE IF NOT EXISTS Clubs (
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
                FOREIGN KEY (ClubId) REFERENCES Clubs(Id) ON DELETE CASCADE
            )
            """)

            # Club Bans table (matching Nadeko's ClubBans)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS ClubBans (
                ClubId INTEGER,
                UserId INTEGER,
                DateAdded TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ClubId, UserId),
                FOREIGN KEY (ClubId) REFERENCES Clubs(Id) ON DELETE CASCADE
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

            # Waifu tables (matching Nadeko structure)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS WaifuInfo (
                    WaifuId INTEGER PRIMARY KEY,
                    ClaimerId INTEGER,
                    Affinity INTEGER,
                    Price INTEGER DEFAULT 50,
                    DateAdded TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS WaifuItem (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT,
                    WaifuInfoId INTEGER,
                    ItemEmoji TEXT,
                    Name TEXT,
                    DateAdded TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (WaifuInfoId) REFERENCES WaifuInfo(WaifuId) ON DELETE CASCADE
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS WaifuUpdates (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT,
                    UserId INTEGER,
                    OldId INTEGER,
                    NewId INTEGER,
                    UpdateType INTEGER,
                    DateAdded TEXT DEFAULT CURRENT_TIMESTAMP
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

            # Bot Configuration table (For system persistence)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS BotConfig (
                    Key TEXT PRIMARY KEY,
                    Value TEXT,
                    Description TEXT
                )
            """)
            
            # User Inventory table (New for v2 - converting Command items)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS UserInventory (
                UserId INTEGER,
                GuildId INTEGER,
                ShopEntryId INTEGER,
                Quantity INTEGER DEFAULT 1,
                DateAdded TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (UserId, GuildId, ShopEntryId),
                FOREIGN KEY (ShopEntryId) REFERENCES ShopEntry(Id) ON DELETE CASCADE
            )
            """)

            # Create Indices for Performance
            await db.execute("CREATE INDEX IF NOT EXISTS idx_xp_guild_xp ON UserXpStats(GuildId, Xp DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_currency_amount ON DiscordUser(CurrencyAmount DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON CurrencyTransactions(UserId)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_club_xp ON Clubs(Xp DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_club ON DiscordUser(ClubId)")
            
            # Optimized indices for Shop System and XP Caching
            await db.execute("CREATE INDEX IF NOT EXISTS idx_shop_entry_items ON ShopEntryItem(ShopEntryId)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_xp_exclusions ON XpExcludedItem(GuildId, ItemId, ItemType)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_shop_entry_guild ON ShopEntry(GuildId, `Index`)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_inventory ON UserInventory(UserId, GuildId)")

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
                
            # Create UserInventory table if it doesn't exist (for existing DBs that missed init)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS UserInventory (
                UserId INTEGER,
                GuildId INTEGER,
                ShopEntryId INTEGER,
                Quantity INTEGER DEFAULT 1,
                DateAdded TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (UserId, GuildId, ShopEntryId),
                FOREIGN KEY (ShopEntryId) REFERENCES ShopEntry(Id) ON DELETE CASCADE
            )
            """)

            # Create BotConfig table if it doesn't exist
            await db.execute("""
                CREATE TABLE IF NOT EXISTS BotConfig (
                    Key TEXT PRIMARY KEY,
                    Value TEXT,
                    Description TEXT
                )
            """)
            
            # Migrate Command items (Type 1) to Items (Type 4)
            # Check if there are any Type 1 items first
            cursor = await db.execute("SELECT COUNT(*) FROM ShopEntry WHERE Type = 1")
            count = (await cursor.fetchone())[0]
            
            if count > 0:
                log.info(f"Migrating {count} 'Command' shop items to 'Item' type...")
                await db.execute("UPDATE ShopEntry SET Type = 4, Command = NULL WHERE Type = 1")
                await db.commit()
                log.info("Migration complete.")
                
        except Exception as e:
            log.error(f"Error updating database schema: {e}")
            
    # Level calculation methods (using Nadeko's exact formula)
    @staticmethod
    def calculate_level_stats(total_xp: int) -> LevelStats:
        """Calculate level statistics from total XP (using Nadeko's formula).
        
        Args:
            total_xp: The total accumulated XP.
            
        Returns:
            LevelStats object containing level breakdown.
        """
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
        """Get level from total XP (Nadeko's formula).
        
        Args:
            total_xp: Total XP.
            
        Returns:
            Calculated level.
        """
        if total_xp < 0:
            total_xp = 0
        return int((-7.0 / 2) + (1 / 6.0 * math.sqrt((8 * total_xp) + 441)))
    
    @staticmethod
    def get_total_xp_req_for_level(level: int) -> int:
        """Get total XP required for a specific level (Nadeko's formula).
        
        Args:
            level: The target level.
            
        Returns:
            Total XP required to reach that level.
        """
        return ((9 * level * level) + (63 * level)) // 2
    
    @staticmethod
    def get_required_xp_for_next_level(level: int) -> int:
        """Get XP required for next level (Nadeko's formula).
        
        Args:
            level: Current level.
            
        Returns:
            XP required to advance to next level.
        """
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
                
                async with nadeko_db.execute("SELECT UserId, Username, AvatarId, TotalXp, CurrencyAmount, ClubId, IsClubAdmin FROM DiscordUser") as cursor:
                    async for row in cursor:
                        # row = (user_id, username, avatar_id, total_xp, currency_amount, club_id, is_club_admin)
                        batch_data.append(row)
                        migrated_users += 1
                        
                        # Process batch when it reaches batch_size
                        if len(batch_data) >= batch_size:
                            async with self._get_connection() as db:
                                await db.executemany("""
                                    INSERT OR REPLACE INTO DiscordUser (UserId, Username, AvatarId, TotalXp, CurrencyAmount, ClubId, IsClubAdmin)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, batch_data)
                                await db.commit()
                            log.info(f"Migrated {migrated_users}/{user_count} users...")
                            batch_data.clear()
                
                # Process remaining batch
                if batch_data:
                    async with self._get_connection() as db:
                        await db.executemany("""
                            INSERT OR REPLACE INTO DiscordUser (UserId, Username, AvatarId, TotalXp, CurrencyAmount, ClubId, IsClubAdmin)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
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
                    # Join with XpSettings to get GuildId
                    query = """
                        SELECT xcr.Id, xs.GuildId, xcr.Level, xcr.Amount 
                        FROM XpCurrencyReward xcr
                        JOIN XpSettings xs ON xcr.XpSettingsId = xs.Id
                    """
                    async with nadeko_db.execute(query) as cursor:
                        async for row in cursor:
                            reward_id, guild_id, level, amount = row
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO XpCurrencyReward (Id, XpSettingsId, Level, Amount)
                                    VALUES (?, ?, ?, ?)
                                """, (reward_id, guild_id, level, amount))
                                await db.commit()
                    log.info("Migrated XP Currency Rewards")
                except Exception as e:
                    log.info(f"XpCurrencyReward migration failed (table might be missing): {e}")
                
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

                # Migrate Waifu Tables
                try:
                    # WaifuInfo - Join with DiscordUser to get Snowflakes
                    # Note: Nadeko stores Internal IDs (int) in WaifuInfo, but Unicornia uses Snowflakes (ulong)
                    query = """
                        SELECT
                            w.UserId as WaifuId,
                            c.UserId as ClaimerId,
                            a.UserId as AffinityId,
                            wi.Price,
                            wi.DateAdded
                        FROM WaifuInfo wi
                        JOIN DiscordUser w ON wi.WaifuId = w.Id
                        LEFT JOIN DiscordUser c ON wi.ClaimerId = c.Id
                        LEFT JOIN DiscordUser a ON wi.AffinityId = a.Id
                    """
                    async with nadeko_db.execute(query) as cursor:
                        async for row in cursor:
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO WaifuInfo (WaifuId, ClaimerId, Affinity, Price, DateAdded)
                                    VALUES (?, ?, ?, ?, ?)
                                """, row)
                                await db.commit()
                    log.info("Migrated WaifuInfo")

                    # WaifuItem - Join to get Snowflake WaifuId via WaifuInfo relation
                    # Nadeko: WaifuItem.WaifuInfoId -> WaifuInfo.Id -> WaifuInfo.WaifuId (internal) -> DiscordUser.Id -> DiscordUser.UserId
                    query = """
                        SELECT
                            w.UserId as WaifuId,
                            itm.ItemEmoji,
                            itm.Name,
                            itm.DateAdded
                        FROM WaifuItem itm
                        JOIN WaifuInfo wi ON itm.WaifuInfoId = wi.Id
                        JOIN DiscordUser w ON wi.WaifuId = w.Id
                    """
                    async with nadeko_db.execute(query) as cursor:
                        async for row in cursor:
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO WaifuItem (WaifuInfoId, ItemEmoji, Name, DateAdded)
                                    VALUES (?, ?, ?, ?)
                                """, row)
                                await db.commit()
                    log.info("Migrated WaifuItem")

                    # WaifuUpdates - Join to get Snowflakes
                    query = """
                        SELECT
                            u.UserId as UserId,
                            o.UserId as OldId,
                            n.UserId as NewId,
                            wu.UpdateType,
                            wu.DateAdded
                        FROM WaifuUpdates wu
                        JOIN DiscordUser u ON wu.UserId = u.Id
                        LEFT JOIN DiscordUser o ON wu.OldId = o.Id
                        LEFT JOIN DiscordUser n ON wu.NewId = n.Id
                    """
                    async with nadeko_db.execute(query) as cursor:
                        async for row in cursor:
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO WaifuUpdates (UserId, OldId, NewId, UpdateType, DateAdded)
                                    VALUES (?, ?, ?, ?, ?)
                                """, row)
                                await db.commit()
                    log.info("Migrated WaifuUpdates")
                except Exception as e:
                    log.warning(f"Waifu migration partial failure: {e}")

                # Migrate Club Tables
                try:
                    # ClubInfo - Join with DiscordUser to get Snowflake OwnerId
                    async with nadeko_db.execute("""
                        SELECT c.Id, c.Name, c.Description, c.ImageUrl, c.BannerUrl, c.Xp, u.UserId, c.DateAdded
                        FROM Clubs c
                        LEFT JOIN DiscordUser u ON c.OwnerId = u.Id
                    """) as cursor:
                        async for row in cursor:
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO Clubs (Id, Name, Description, ImageUrl, BannerUrl, Xp, OwnerId, DateAdded)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """, row)
                                await db.commit()
                    log.info("Migrated Clubs")

                    # ClubApplicants - Join with DiscordUser to get Snowflake UserId
                    async with nadeko_db.execute("""
                        SELECT ca.ClubId, u.UserId
                        FROM ClubApplicants ca
                        JOIN DiscordUser u ON ca.UserId = u.Id
                    """) as cursor:
                        async for row in cursor:
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO ClubApplicants (ClubId, UserId)
                                    VALUES (?, ?)
                                """, row)
                                await db.commit()
                    log.info("Migrated ClubApplicants")

                    # ClubBans - Join with DiscordUser to get Snowflake UserId
                    async with nadeko_db.execute("""
                        SELECT cb.ClubId, u.UserId
                        FROM ClubBans cb
                        JOIN DiscordUser u ON cb.UserId = u.Id
                    """) as cursor:
                        async for row in cursor:
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO ClubBans (ClubId, UserId)
                                    VALUES (?, ?)
                                """, row)
                                await db.commit()
                    log.info("Migrated ClubBans")
                except Exception as e:
                    log.warning(f"Club migration partial failure: {e}")

                # Migrate XP Configuration
                # XpSettings
                try:
                    async with nadeko_db.execute("SELECT GuildId, XpRateMultiplier, XpPerMessage, XpMinutesTimeout FROM XpSettings") as cursor:
                        async for row in cursor:
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO XpSettings (GuildId, XpRateMultiplier, XpPerMessage, XpMinutesTimeout)
                                    VALUES (?, ?, ?, ?)
                                """, row)
                                await db.commit()
                    log.info("Migrated XP Settings")
                except Exception as e:
                    log.warning(f"XP Settings migration partial failure: {e}")

                # XpRoleReward
                try:
                    # Join with XpSettings to get GuildId
                    query = """
                        SELECT xs.GuildId, xrr.Level, xrr.RoleId, xrr.Remove
                        FROM XpRoleReward xrr
                        JOIN XpSettings xs ON xrr.XpSettingsId = xs.Id
                    """
                    rewards_migrated = 0
                    async with nadeko_db.execute(query) as cursor:
                        async for row in cursor:
                            guild_id, level, role_id, remove = row
                            async with self._get_connection() as db:
                                # Ensure Remove is boolean (0 or 1)
                                remove_bool = 1 if remove else 0
                                await db.execute("""
                                    INSERT OR REPLACE INTO XpRoleReward (GuildId, Level, RoleId, Remove)
                                    VALUES (?, ?, ?, ?)
                                """, (guild_id, level, role_id, remove_bool))
                                await db.commit()
                            rewards_migrated += 1
                    
                    log.info(f"Migrated {rewards_migrated} XP Role Rewards using JOIN")

                    # Fallback if 0 rewards found: Try manual mapping
                    if rewards_migrated == 0:
                        log.info("Attempting manual mapping fallback for Role Rewards...")
                        
                        # 1. Fetch all XpSettings to build {Id: GuildId} map
                        xp_settings_map = {}
                        try:
                            async with nadeko_db.execute("SELECT Id, GuildId FROM XpSettings") as cursor:
                                async for row in cursor:
                                    xp_settings_map[row[0]] = row[1]
                            log.info(f"Loaded {len(xp_settings_map)} XpSettings mappings.")
                        except Exception as e:
                            log.error(f"Failed to load XpSettings for fallback: {e}")
                        
                        if not xp_settings_map:
                            log.warning("No XpSettings found, cannot migrate Role Rewards.")
                        else:
                            # 2. Fetch all XpRoleReward and map manually
                            try:
                                async with nadeko_db.execute("SELECT XpSettingsId, Level, RoleId, Remove FROM XpRoleReward") as cursor:
                                    async for row in cursor:
                                        xp_settings_id, level, role_id, remove = row
                                        if xp_settings_id in xp_settings_map:
                                            guild_id = xp_settings_map[xp_settings_id]
                                            async with self._get_connection() as db:
                                                remove_bool = 1 if remove else 0
                                                await db.execute("""
                                                    INSERT OR REPLACE INTO XpRoleReward (GuildId, Level, RoleId, Remove)
                                                    VALUES (?, ?, ?, ?)
                                                """, (guild_id, level, role_id, remove_bool))
                                                await db.commit()
                                            rewards_migrated += 1
                                        else:
                                            log.warning(f"Skipping Role Reward with unknown XpSettingsId: {xp_settings_id}")
                                log.info(f"Migrated {rewards_migrated} XP Role Rewards using fallback mapping")
                            except Exception as e:
                                log.error(f"Failed to fetch XpRoleReward for fallback: {e}")

                except Exception as e:
                    log.warning(f"XP Role Rewards migration failure: {e}")
                
                # XpExcludedItem migration removed (Whitelisted channels are now in Red Config)

                # Migrate XpShopOwnedItem
                try:
                    cursor = await nadeko_db.execute("SELECT COUNT(*) FROM XpShopOwnedItem")
                    count = (await cursor.fetchone())[0]
                    log.info(f"Found {count} XP Shop items to migrate")

                    migrated_items = 0
                    batch_data = []

                    async with nadeko_db.execute("SELECT UserId, ItemType, IsUsing, ItemKey FROM XpShopOwnedItem") as cursor:
                        async for row in cursor:
                            # row: (UserId, ItemType, IsUsing, ItemKey)
                            batch_data.append(row)
                            migrated_items += 1
                            
                            if len(batch_data) >= 1000:
                                async with self._get_connection() as db:
                                    await db.executemany("""
                                        INSERT OR REPLACE INTO XpShopOwnedItem (UserId, ItemType, IsUsing, ItemKey)
                                        VALUES (?, ?, ?, ?)
                                    """, batch_data)
                                    await db.commit()
                                batch_data.clear()
                    
                    if batch_data:
                        async with self._get_connection() as db:
                            await db.executemany("""
                                INSERT OR REPLACE INTO XpShopOwnedItem (UserId, ItemType, IsUsing, ItemKey)
                                VALUES (?, ?, ?, ?)
                            """, batch_data)
                            await db.commit()

                    log.info(f"Migrated {migrated_items} XP Shop Owned Items")
                except Exception as e:
                    log.warning(f"XP Shop Owned Items migration partial failure: {e}")

                # Migrate Gambling Stats
                try:
                    # GamblingStats
                    async with nadeko_db.execute("SELECT Feature, BetAmount, WinAmount, LossAmount FROM GamblingStats") as cursor:
                        async for row in cursor:
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO GamblingStats (Feature, BetAmount, WinAmount, LossAmount)
                                    VALUES (?, ?, ?, ?)
                                """, row)
                                await db.commit()

                    # UserBetStats
                    async with nadeko_db.execute("SELECT UserId, Game, BetAmount, WinAmount, LossAmount, MaxWin FROM UserBetStats") as cursor:
                        async for row in cursor:
                            async with self._get_connection() as db:
                                await db.execute("""
                                    INSERT OR REPLACE INTO UserBetStats (UserId, Game, BetAmount, WinAmount, LossAmount, MaxWin)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                """, row)
                                await db.commit()
                    log.info("Migrated Gambling Stats")
                except Exception as e:
                    log.warning(f"Gambling stats migration partial failure: {e}")
                
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
                "CurrencyTransactions",
                "BankUsers",
                "TimelyCooldown",
                "WaifuInfo",  # Remove waifu claims
                "WaifuUpdates",  # Remove waifu history
                "XpShopOwnedItem",
                "UserInventory"
            ]
            
            for table in tables_to_clean:
                try:
                    await db.execute(f"DELETE FROM {table} WHERE UserId = ?", (user_id,))
                except Exception as e:
                    # Some tables might not exist or have different column names
                    log.warning(f"Could not clean table {table} for user {user_id}: {e}")
            
            # Clean waifu tables with different column names
            try:
                await db.execute("DELETE FROM WaifuInfo WHERE ClaimerId = ?", (user_id,))
            except Exception:
                pass
                
            try:
                await db.execute("DELETE FROM WaifuUpdates WHERE OldId = ? OR NewId = ?", (user_id, user_id))
            except Exception:
                pass
            
            await db.commit()
            log.info(f"Deleted all data for user {user_id}")
