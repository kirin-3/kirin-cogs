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
                    TotalXp INTEGER DEFAULT 0 CHECK (TotalXp >= 0),
                    CurrencyAmount INTEGER DEFAULT 0 CHECK (CurrencyAmount >= 0)
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS UserXpStats (
                    UserId INTEGER,
                    GuildId INTEGER,
                    Xp INTEGER DEFAULT 0 CHECK (Xp >= 0),
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
                    Amount INTEGER CHECK (Amount > 0),
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
                Balance INTEGER NOT NULL DEFAULT 0 CHECK (Balance >= 0)
            )
            """)
            
            # Gambling Stats table (matching Nadeko's GamblingStats)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS GamblingStats (
                Feature TEXT PRIMARY KEY,
                BetAmount INTEGER NOT NULL DEFAULT 0 CHECK (BetAmount >= 0),
                WinAmount INTEGER NOT NULL DEFAULT 0 CHECK (WinAmount >= 0),
                LossAmount INTEGER NOT NULL DEFAULT 0 CHECK (LossAmount >= 0)
            )
            """)
            
            # User Bet Stats table (matching Nadeko's UserBetStats)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS UserBetStats (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                UserId INTEGER NOT NULL,
                Game TEXT NOT NULL,
                BetAmount INTEGER NOT NULL DEFAULT 0 CHECK (BetAmount >= 0),
                WinAmount INTEGER NOT NULL DEFAULT 0 CHECK (WinAmount >= 0),
                LossAmount INTEGER NOT NULL DEFAULT 0 CHECK (LossAmount >= 0),
                MaxWin INTEGER NOT NULL DEFAULT 0 CHECK (MaxWin >= 0),
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
                Xp INTEGER DEFAULT 0 CHECK (Xp >= 0),
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
                RakebackBalance INTEGER NOT NULL DEFAULT 0 CHECK (RakebackBalance >= 0)
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
                    Price INTEGER CHECK (Price >= 0),
                    Name TEXT,
                    AuthorId INTEGER,
                    Type INTEGER,
                    RoleName TEXT,
                    RoleId INTEGER,
                    RoleRequirement INTEGER CHECK (RoleRequirement >= 0),
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
                    Price INTEGER DEFAULT 50 CHECK (Price >= 0),
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
                    Amount INTEGER CHECK (Amount > 0)
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
            
            # User Inventory table (New for v2 - converting Command items)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS UserInventory (
                UserId INTEGER,
                GuildId INTEGER,
                ShopEntryId INTEGER,
                Quantity INTEGER DEFAULT 1 CHECK (Quantity > 0),
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
        possible_paths = [
            self.nadeko_db_path,
            "/data/nadeko.db",
            "data/nadeko.db",
            "nadeko.db",
            "data/nadeko/nadeko.db"
        ]
        
        nadeko_db_path = next((path for path in possible_paths if path and Path(path).exists()), None)
        
        if not nadeko_db_path:
            log.info("No Nadeko database found, skipping migration.")
            return

        log.info(f"Starting migration from Nadeko database at {nadeko_db_path}...")
        
        try:
            async with aiosqlite.connect(nadeko_db_path) as nadeko_db, self._get_connection() as db:
                # Use a single transaction for the entire migration for atomicity
                await db.execute("BEGIN")
                
                try:
                    # Helper to execute batch migration for a table
                    async def batch_migrate(table_name, select_query, insert_query, params_transform=None):
                        log.info(f"Migrating {table_name}...")
                        data = []
                        async with nadeko_db.execute(select_query) as cursor:
                            async for row in cursor:
                                data.append(params_transform(row) if params_transform else row)
                        
                        if data:
                            await db.executemany(insert_query, data)
                            log.info(f"Migrated {len(data)} records for {table_name}")

                    # --- DiscordUser and UserXpStats (already batched, but integrated here) ---
                    discord_user_data = await nadeko_db.execute_fetchall("SELECT UserId, Username, AvatarId, TotalXp, CurrencyAmount, ClubId, IsClubAdmin FROM DiscordUser")
                    if discord_user_data:
                        await db.executemany("INSERT OR REPLACE INTO DiscordUser (UserId, Username, AvatarId, TotalXp, CurrencyAmount, ClubId, IsClubAdmin) VALUES (?, ?, ?, ?, ?, ?, ?)", discord_user_data)

                    user_xp_stats_data = await nadeko_db.execute_fetchall("SELECT UserId, GuildId, Xp FROM UserXpStats")
                    if user_xp_stats_data:
                        await db.executemany("INSERT OR REPLACE INTO UserXpStats (UserId, GuildId, Xp) VALUES (?, ?, ?)", user_xp_stats_data)

                    # --- Other Tables (now batched) ---
                    await batch_migrate("BankUsers", "SELECT UserId, Balance FROM BankUsers", "INSERT OR REPLACE INTO BankUsers (UserId, Balance) VALUES (?, ?)")
                    await batch_migrate("PlantedCurrency", "SELECT GuildId, ChannelId, UserId, MessageId, Amount, Password FROM PlantedCurrency", "INSERT OR REPLACE INTO PlantedCurrency (GuildId, ChannelId, UserId, MessageId, Amount, Password) VALUES (?, ?, ?, ?, ?, ?)")
                    await batch_migrate("ShopEntry", "SELECT Id, GuildId, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command FROM ShopEntry", "INSERT OR REPLACE INTO ShopEntry (Id, GuildId, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
                    await batch_migrate("ShopEntryItem", "SELECT Id, ShopEntryId, Text FROM ShopEntryItem", "INSERT OR REPLACE INTO ShopEntryItem (Id, ShopEntryId, Text) VALUES (?, ?, ?)")

                    # Waifu Tables
                    await batch_migrate("WaifuInfo", "SELECT w.UserId, c.UserId, a.UserId, wi.Price, wi.DateAdded FROM WaifuInfo wi JOIN DiscordUser w ON wi.WaifuId = w.Id LEFT JOIN DiscordUser c ON wi.ClaimerId = c.Id LEFT JOIN DiscordUser a ON wi.AffinityId = a.Id", "INSERT OR REPLACE INTO WaifuInfo (WaifuId, ClaimerId, Affinity, Price, DateAdded) VALUES (?, ?, ?, ?, ?)")
                    await batch_migrate("WaifuItem", "SELECT w.UserId, itm.ItemEmoji, itm.Name, itm.DateAdded FROM WaifuItem itm JOIN WaifuInfo wi ON itm.WaifuInfoId = wi.Id JOIN DiscordUser w ON wi.WaifuId = w.Id", "INSERT OR REPLACE INTO WaifuItem (WaifuInfoId, ItemEmoji, Name, DateAdded) VALUES (?, ?, ?, ?)")
                    await batch_migrate("WaifuUpdates", "SELECT u.UserId, o.UserId, n.UserId, wu.UpdateType, wu.DateAdded FROM WaifuUpdates wu JOIN DiscordUser u ON wu.UserId = u.Id LEFT JOIN DiscordUser o ON wu.OldId = o.Id LEFT JOIN DiscordUser n ON wu.NewId = n.Id", "INSERT OR REPLACE INTO WaifuUpdates (UserId, OldId, NewId, UpdateType, DateAdded) VALUES (?, ?, ?, ?, ?)")

                    # Club Tables
                    await batch_migrate("Clubs", "SELECT c.Id, c.Name, c.Description, c.ImageUrl, c.BannerUrl, c.Xp, u.UserId, c.DateAdded FROM Clubs c LEFT JOIN DiscordUser u ON c.OwnerId = u.Id", "INSERT OR REPLACE INTO Clubs (Id, Name, Description, ImageUrl, BannerUrl, Xp, OwnerId, DateAdded) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
                    await batch_migrate("ClubApplicants", "SELECT ca.ClubId, u.UserId FROM ClubApplicants ca JOIN DiscordUser u ON ca.UserId = u.Id", "INSERT OR REPLACE INTO ClubApplicants (ClubId, UserId) VALUES (?, ?)")
                    await batch_migrate("ClubBans", "SELECT cb.ClubId, u.UserId FROM ClubBans cb JOIN DiscordUser u ON cb.UserId = u.Id", "INSERT OR REPLACE INTO ClubBans (ClubId, UserId) VALUES (?, ?)")

                    # XP Config
                    await batch_migrate("XpSettings", "SELECT GuildId, XpRateMultiplier, XpPerMessage, XpMinutesTimeout FROM XpSettings", "INSERT OR REPLACE INTO XpSettings (GuildId, XpRateMultiplier, XpPerMessage, XpMinutesTimeout) VALUES (?, ?, ?, ?)")
                    
                    # Role Rewards with fallback
                    rewards_query = "SELECT xs.GuildId, xrr.Level, xrr.RoleId, xrr.Remove FROM XpRoleReward xrr JOIN XpSettings xs ON xrr.XpSettingsId = xs.Id"
                    rewards_data = await nadeko_db.execute_fetchall(rewards_query)
                    if rewards_data:
                        await db.executemany("INSERT OR REPLACE INTO XpRoleReward (GuildId, Level, RoleId, Remove) VALUES (?, ?, ?, ?)", [(g, l, r, 1 if rem else 0) for g, l, r, rem in rewards_data])
                    else:
                        # Fallback logic
                        settings_map = {row[0]: row[1] for row in await nadeko_db.execute_fetchall("SELECT Id, GuildId FROM XpSettings")}
                        if settings_map:
                            rewards_fallback_data = await nadeko_db.execute_fetchall("SELECT XpSettingsId, Level, RoleId, Remove FROM XpRoleReward")
                            rewards_to_insert = [(settings_map[sid], l, rid, 1 if rem else 0) for sid, l, rid, rem in rewards_fallback_data if sid in settings_map]
                            if rewards_to_insert:
                                await db.executemany("INSERT OR REPLACE INTO XpRoleReward (GuildId, Level, RoleId, Remove) VALUES (?, ?, ?, ?)", rewards_to_insert)

                    # Shop Items
                    await batch_migrate("XpShopOwnedItem", "SELECT UserId, ItemType, IsUsing, ItemKey FROM XpShopOwnedItem", "INSERT OR REPLACE INTO XpShopOwnedItem (UserId, ItemType, IsUsing, ItemKey) VALUES (?, ?, ?, ?)")

                    # Gambling Stats
                    await batch_migrate("GamblingStats", "SELECT Feature, BetAmount, WinAmount, LossAmount FROM GamblingStats", "INSERT OR REPLACE INTO GamblingStats (Feature, BetAmount, WinAmount, LossAmount) VALUES (?, ?, ?, ?)")
                    await batch_migrate("UserBetStats", "SELECT UserId, Game, BetAmount, WinAmount, LossAmount, MaxWin FROM UserBetStats", "INSERT OR REPLACE INTO UserBetStats (UserId, Game, BetAmount, WinAmount, LossAmount, MaxWin) VALUES (?, ?, ?, ?, ?, ?)")

                    await db.commit()
                    log.info("Migration from Nadeko database completed successfully")
                
                except Exception:
                    await db.execute("ROLLBACK")
                    log.error("Migration failed, rolling back changes.")
                    raise

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
                except aiosqlite.Error as e:
                    # Some tables might not exist or have different column names
                    log.warning(f"Could not clean table {table} for user {user_id}: {e}")
            
            # Clean waifu tables with different column names
            try:
                await db.execute("DELETE FROM WaifuInfo WHERE ClaimerId = ?", (user_id,))
            except aiosqlite.Error:
                pass
                
            try:
                await db.execute("DELETE FROM WaifuUpdates WHERE OldId = ? OR NewId = ?", (user_id, user_id))
            except aiosqlite.Error:
                pass
            
            await db.commit()
            log.info(f"Deleted all data for user {user_id}")
