"""
Core Database Logic
"""

import asyncio
import json
import logging
import math
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import aiosqlite

from ..types import LevelStats

log = logging.getLogger("red.kirin_cogs.unicornia.database")


class CoreDB:
    """Core database functionality"""

    def __init__(
        self,
        db_path: str,
        *,
        reconcile_reserved_on_initialize: bool = True,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.reconcile_reserved_on_initialize = reconcile_reserved_on_initialize
        self._conn: aiosqlite.Connection | None = None
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
    async def _get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Yield the persistent database connection"""
        async with self._lock:
            if self._conn is None:
                await self.connect()
            assert self._conn is not None, "Database connection is not established"
            try:
                yield self._conn
            except BaseException:
                # A caller that fails mid-transaction (a failed COMMIT included) must not
                # leave it open on the shared connection, or every later BEGIN fails with
                # "cannot start a transaction within a transaction".
                if self._conn is not None and self._conn.in_transaction:
                    try:
                        await self._conn.rollback()
                    except Exception:
                        log.exception("Could not roll back after a failed database operation")
                raise

    async def _setup_wal_mode(self, db: aiosqlite.Connection) -> None:
        """Set up WAL mode and optimizations for a database connection.

        Args:
            db: The database connection to configure.
        """
        # Fetch (and thereby close) every PRAGMA cursor: some of these return a
        # row, and a cursor with an unfetched row keeps its statement active on
        # the shared connection. Committing with an active statement fails with
        # "cannot commit transaction - SQL statements in progress", and the
        # failed commit leaves the transaction open, wedging every later query.
        for pragma in (
            "PRAGMA journal_mode=WAL",
            "PRAGMA foreign_keys=ON",
            "PRAGMA synchronous=NORMAL",
            # Negative value = pages in KiB (4000KB ~ 4MB) -> actually let's use pages. Positive = pages. 4000 pages * 4KB = 16MB.
            "PRAGMA cache_size=-4000",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA mmap_size=33554432",  # 32MB memory mapping (Safe for 1GB VPS)
            "PRAGMA page_size=4096",  # 4KB page size
            "PRAGMA auto_vacuum=INCREMENTAL",  # Incremental vacuum
        ):
            cursor = await db.execute(pragma)
            await cursor.fetchall()

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
                if mode and mode[0] != "wal":
                    log.warning("Database not in WAL mode, attempting to enable...")
                    cursor = await db.execute("PRAGMA journal_mode=WAL")
                    await cursor.fetchall()
                    await db.commit()

                # Perform WAL checkpoint to prevent WAL file from growing too large
                # Using PASSIVE to avoid locking the database
                cursor = await db.execute("PRAGMA wal_checkpoint(PASSIVE)")
                await cursor.fetchall()

            # The check reads the whole file, so it runs outside the shared connection's lock
            result = await self._quick_check()
            if result != "ok":
                log.error(f"Database integrity check failed: {result}")
                return False
            return True
        except Exception as e:
            log.error(f"WAL integrity check failed: {e}")
            return False

    async def _quick_check(self) -> str:
        """Run PRAGMA quick_check on a separate read-only connection.

        In WAL mode a reader doesn't block writers, so economy commands keep running on the
        shared connection while the check reads the file.
        """
        uri = f"{self.db_path.resolve().as_uri()}?mode=ro"
        async with aiosqlite.connect(uri, uri=True) as db:
            cursor = await db.execute("PRAGMA quick_check")
            row = await cursor.fetchone()
        return str(row[0]) if row else "no result"

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

            # Idempotent economy operations (additive; keyed by caller-supplied
            # idempotency key so retries never repeat a balance effect)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS EconomyOperations (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                OperationKey TEXT NOT NULL UNIQUE,
                GuildId INTEGER,
                UserId INTEGER NOT NULL,
                Source TEXT NOT NULL,
                Direction TEXT NOT NULL,
                Amount INTEGER NOT NULL,
                State TEXT NOT NULL,
                Result TEXT,
                CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                SettledAt TEXT
            )
            """)

            # Gambling Stats table (matching Nadeko's GamblingStats)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS GamblingStats (
                Feature TEXT PRIMARY KEY,
                BetAmount INTEGER NOT NULL DEFAULT 0,
                WinAmount INTEGER NOT NULL DEFAULT 0,
                LossAmount INTEGER NOT NULL DEFAULT 0,
                Rounds INTEGER NOT NULL DEFAULT 0,
                StakedSinceEpoch INTEGER NOT NULL DEFAULT 0,
                PaidOut INTEGER NOT NULL DEFAULT 0,
                RakebackPaid INTEGER NOT NULL DEFAULT 0,
                EpochStart TEXT
            )
            """)

            await db.execute("""
            CREATE TABLE IF NOT EXISTS YieldPool (
                Id INTEGER PRIMARY KEY CHECK (Id = 1),
                Balance INTEGER NOT NULL DEFAULT 0,
                LifetimeHouseBanked INTEGER NOT NULL DEFAULT 0,
                LifetimePooled INTEGER NOT NULL DEFAULT 0,
                LifetimeTradeTax INTEGER NOT NULL DEFAULT 0,
                NextDistributionAt TEXT,
                UpdatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)
            await db.execute("""
                INSERT OR IGNORE INTO YieldPool
                    (Id, Balance, LifetimeHouseBanked, LifetimePooled, LifetimeTradeTax)
                VALUES (1, 0, 0, 0, 0)
            """)

            await db.execute("""
            CREATE TABLE IF NOT EXISTS DividendRuns (
                PeriodEnd TEXT PRIMARY KEY,
                Distributed INTEGER NOT NULL,
                Recipients INTEGER NOT NULL,
                CompletedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS DividendPayouts (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                PeriodEnd TEXT NOT NULL,
                UserId INTEGER NOT NULL,
                Symbol TEXT NOT NULL,
                Weight REAL NOT NULL,
                Amount INTEGER NOT NULL,
                DateAdded TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_dividend_payouts_user_period ON DividendPayouts(UserId, PeriodEnd)"
            )

            await db.execute("""
            CREATE TABLE IF NOT EXISTS SpectatorMarkets (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                HandKey TEXT NOT NULL UNIQUE,
                State TEXT NOT NULL,
                OpenedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                ClosedAt TEXT,
                Outcome TEXT
            )
            """)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS SpectatorBets (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                MarketId INTEGER NOT NULL,
                UserId INTEGER NOT NULL,
                Side TEXT NOT NULL,
                Amount INTEGER NOT NULL,
                StakeKey TEXT NOT NULL UNIQUE,
                UNIQUE(MarketId, UserId),
                FOREIGN KEY (MarketId) REFERENCES SpectatorMarkets(Id) ON DELETE CASCADE
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

            # Club Invitations table
            await db.execute("""
            CREATE TABLE IF NOT EXISTS ClubInvitations (
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

            await db.executemany(
                """
                INSERT OR IGNORE INTO BotConfig (Key, Value, Description)
                VALUES (?, ?, ?)
                """,
                [
                    ("LastMarketTick", None, "Timestamp of last completed market tick"),
                    ("StockLedgerBackfilled", "0", "Whether legacy stock transactions were imported"),
                    ("DividendAccumulationStart", None, "Start of the retained dividend usage window"),
                ],
            )

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

            # Unicorn stable (idle game): the coin box and the unicorns
            await db.execute("""
            CREATE TABLE IF NOT EXISTS Stable (
                UserId INTEGER PRIMARY KEY,
                Box REAL NOT NULL DEFAULT 0,
                LastSettle REAL NOT NULL,
                BoxSize INTEGER NOT NULL DEFAULT 0
            )
            """)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS StableUnicorn (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                UserId INTEGER NOT NULL,
                Breed TEXT NOT NULL,
                Level INTEGER NOT NULL DEFAULT 1,
                Name TEXT,
                DateAdded TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_stable_unicorn_user ON StableUnicorn(UserId)")

            # Create Indices for Performance
            await db.execute("CREATE INDEX IF NOT EXISTS idx_xp_guild_xp ON UserXpStats(GuildId, Xp DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_currency_amount ON DiscordUser(CurrencyAmount DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON CurrencyTransactions(UserId)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_club_xp ON Clubs(Xp DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_club ON DiscordUser(ClubId)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_economy_operations_user ON EconomyOperations(UserId)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_economy_operations_state ON EconomyOperations(State)")

            # Optimized indices for Shop System and XP Caching
            await db.execute("CREATE INDEX IF NOT EXISTS idx_shop_entry_items ON ShopEntryItem(ShopEntryId)")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_xp_exclusions ON XpExcludedItem(GuildId, ItemId, ItemType)"
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_shop_entry_guild ON ShopEntry(GuildId, `Index`)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_user_inventory ON UserInventory(UserId, GuildId)")

            # Stock Market tables
            await db.execute("""
                CREATE TABLE IF NOT EXISTS Stocks (
                    Symbol TEXT PRIMARY KEY,
                    Name TEXT,
                    Emoji TEXT,
                    CurrentPrice INTEGER,
                    PreviousPrice INTEGER,
                    TotalShares INTEGER DEFAULT 0,
                    ShareReserve REAL DEFAULT 100000,
                    SmoothedUsage REAL DEFAULT 0,
                    PeriodUsage INTEGER NOT NULL DEFAULT 0,
                    Volatility REAL DEFAULT 1.0,
                    Hidden INTEGER DEFAULT 0
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS StockHoldings (
                    UserId INTEGER,
                    Symbol TEXT,
                    Amount INTEGER,
                    AverageCost REAL,
                    PRIMARY KEY (UserId, Symbol),
                    FOREIGN KEY (Symbol) REFERENCES Stocks(Symbol) ON DELETE CASCADE
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS StockTransactions (
                    Id INTEGER PRIMARY KEY AUTOINCREMENT,
                    UserId INTEGER NOT NULL,
                    Symbol TEXT NOT NULL,
                    Side TEXT NOT NULL CHECK (Side IN ('buy', 'sell')),
                    Kind TEXT NOT NULL DEFAULT 'trade',
                    Shares INTEGER NOT NULL,
                    ExecPrice REAL NOT NULL,
                    Tax INTEGER NOT NULL,
                    TotalAmount INTEGER NOT NULL,
                    IsImported INTEGER NOT NULL DEFAULT 0,
                    DateAdded TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_stock_transactions_user_symbol ON StockTransactions(UserId, Symbol)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_stock_transactions_symbol_date ON StockTransactions(Symbol, DateAdded)"
            )

            await db.commit()

            # Run schema updates for existing databases
            await self._update_database_schema(db)
            if self.reconcile_reserved_on_initialize:
                # Compatibility for direct DatabaseManager consumers. The live
                # cog disables this and runs the configurable age-aware sweeper
                # through EconomyRepository instead.
                await self._reconcile_reserved_economy_operations(db)

    async def _reconcile_reserved_economy_operations(self, db: aiosqlite.Connection) -> int:
        """Refund stake reservations that cannot be resumed after a restart."""
        await db.commit()
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                """
                SELECT OperationKey, UserId, Amount
                FROM EconomyOperations
                WHERE State = 'reserved'
                """
            )
            reservations = await cursor.fetchall()
            reconciled = 0
            payload = json.dumps({"result": "restart_refund"})
            for operation_key, user_id, amount in reservations:
                claim = await db.execute(
                    """
                    UPDATE EconomyOperations
                    SET State = 'settled', Result = ?, SettledAt = datetime('now')
                    WHERE OperationKey = ? AND State = 'reserved'
                    """,
                    (payload, operation_key),
                )
                if claim.rowcount == 0:
                    continue
                await db.execute(
                    """
                    INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                    ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
                    """,
                    (user_id, amount, amount),
                )
                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions
                        (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, 'gambling_refund', 'restart_reconciliation', NULL,
                            'Refunded interrupted game stake', datetime('now'))
                    """,
                    (user_id, amount),
                )
                reconciled += 1
            await db.commit()
        except Exception:
            await db.execute("ROLLBACK")
            raise

        if reconciled:
            log.warning("Refunded %s interrupted gambling stake reservation(s)", reconciled)
        return reconciled

    async def _update_database_schema(self, db):
        """Update existing database schema to add missing columns"""
        try:
            # Check if IsUsing column exists in XpShopOwnedItem table
            cursor = await db.execute("PRAGMA table_info(XpShopOwnedItem)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]  # Column name is at index 1

            if "IsUsing" not in column_names:
                log.info("Adding IsUsing column to XpShopOwnedItem table")
                await db.execute("ALTER TABLE XpShopOwnedItem ADD COLUMN IsUsing BOOLEAN DEFAULT FALSE")
                await db.commit()
                log.info("Successfully added IsUsing column")

            cursor = await db.execute("PRAGMA table_info(Stocks)")
            stock_columns = {row[1] for row in await cursor.fetchall()}
            if "ShareReserve" not in stock_columns:
                await db.execute("ALTER TABLE Stocks ADD COLUMN ShareReserve REAL DEFAULT 100000")
            if "SmoothedUsage" not in stock_columns:
                await db.execute("ALTER TABLE Stocks ADD COLUMN SmoothedUsage REAL DEFAULT 0")
            if "PeriodUsage" not in stock_columns:
                await db.execute("ALTER TABLE Stocks ADD COLUMN PeriodUsage INTEGER NOT NULL DEFAULT 0")

            cursor = await db.execute("PRAGMA table_info(GamblingStats)")
            gambling_columns = {row[1] for row in await cursor.fetchall()}
            for column_name, declaration in (
                ("Rounds", "INTEGER NOT NULL DEFAULT 0"),
                ("StakedSinceEpoch", "INTEGER NOT NULL DEFAULT 0"),
                ("PaidOut", "INTEGER NOT NULL DEFAULT 0"),
                ("RakebackPaid", "INTEGER NOT NULL DEFAULT 0"),
                ("EpochStart", "TEXT"),
            ):
                if column_name not in gambling_columns:
                    await db.execute(f"ALTER TABLE GamblingStats ADD COLUMN {column_name} {declaration}")

            cursor = await db.execute("PRAGMA table_info(StockTransactions)")
            transaction_columns = {row[1] for row in await cursor.fetchall()}
            if "Kind" not in transaction_columns:
                await db.execute("ALTER TABLE StockTransactions ADD COLUMN Kind TEXT NOT NULL DEFAULT 'trade'")
            await db.commit()

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

            # Create ClubInvitations table if it doesn't exist
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ClubInvitations (
                ClubId INTEGER,
                UserId INTEGER,
                DateAdded TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ClubId, UserId),
                FOREIGN KEY (ClubId) REFERENCES Clubs(Id) ON DELETE CASCADE
            )
            """)

            # Create EconomyOperations table if it doesn't exist (existing DBs)
            await db.execute("""
            CREATE TABLE IF NOT EXISTS EconomyOperations (
                Id INTEGER PRIMARY KEY AUTOINCREMENT,
                OperationKey TEXT NOT NULL UNIQUE,
                GuildId INTEGER,
                UserId INTEGER NOT NULL,
                Source TEXT NOT NULL,
                Direction TEXT NOT NULL,
                Amount INTEGER NOT NULL,
                State TEXT NOT NULL,
                Result TEXT,
                CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                SettledAt TEXT
            )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_economy_operations_user ON EconomyOperations(UserId)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_economy_operations_state ON EconomyOperations(State)")

            # Migrate Command items (Type 1) to Items (Type 4)
            # Check if there are any Type 1 items first
            cursor = await db.execute("SELECT COUNT(*) FROM ShopEntry WHERE Type = 1")
            count = (await cursor.fetchone())[0]

            if count > 0:
                log.info(f"Migrating {count} 'Command' shop items to 'Item' type...")
                await db.execute("UPDATE ShopEntry SET Type = 4, Command = NULL WHERE Type = 1")
                await db.commit()
                log.info("Migration complete.")

            # Once: users deleted before deletion subtracted their shares left them counted in TotalShares.
            # Not on every start, since an interrupted stock unwind leaves the two apart until it resumes.
            cursor = await db.execute("SELECT 1 FROM BotConfig WHERE Key = 'TotalSharesRecounted'")
            if await cursor.fetchone() is None:
                await db.execute(
                    """
                    UPDATE Stocks SET TotalShares = (
                        SELECT COALESCE(SUM(Amount), 0) FROM StockHoldings WHERE Symbol = Stocks.Symbol)
                    """
                )
                await db.execute(
                    """
                    INSERT INTO BotConfig (Key, Value, Description)
                    VALUES ('TotalSharesRecounted', '1', 'Whether TotalShares was recounted from holdings')
                    """
                )
                await db.commit()

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

        return LevelStats(level=level, level_xp=level_xp, required_xp=required_xp, total_xp=total_xp)

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

    # Data deletion methods for Red bot compliance
    async def delete_user_data(self, user_id: int):
        """Delete all data for a user (Red bot requirement)"""
        async with self._get_connection() as db:
            # Preserve accounting rows while removing direct identifiers and
            # free-form metadata that may contain personal information.
            await db.execute(
                """
                UPDATE CurrencyTransactions
                SET UserId = 0, OtherId = CASE WHEN OtherId = ? THEN 0 ELSE OtherId END,
                    Reason = '[deleted user]', Extra = NULL
                WHERE UserId = ? OR OtherId = ?
                """,
                (user_id, user_id, user_id),
            )
            await db.execute(
                """
                UPDATE EconomyOperations
                SET UserId = 0, OperationKey = 'deleted:' || lower(hex(randomblob(16))), Result = NULL
                WHERE UserId = ?
                """,
                (user_id,),
            )
            with suppress(aiosqlite.OperationalError):
                await db.execute("UPDATE StockTransactions SET UserId = 0 WHERE UserId = ?", (user_id,))
            # Their holdings are deleted below, so stop counting those shares as held
            with suppress(aiosqlite.OperationalError):
                await db.execute(
                    """
                    UPDATE Stocks SET TotalShares = MAX(0, TotalShares - (
                        SELECT Amount FROM StockHoldings WHERE UserId = ? AND Symbol = Stocks.Symbol))
                    WHERE Symbol IN (SELECT Symbol FROM StockHoldings WHERE UserId = ?)
                    """,
                    (user_id, user_id),
                )
            with suppress(aiosqlite.OperationalError):
                await db.execute("UPDATE DividendPayouts SET UserId = 0 WHERE UserId = ?", (user_id,))

            # Remove direct identifiers from retained shared records.
            with suppress(aiosqlite.OperationalError):
                await db.execute("UPDATE Clubs SET OwnerId = 0 WHERE OwnerId = ?", (user_id,))
            with suppress(aiosqlite.OperationalError):
                await db.execute("UPDATE ShopEntry SET AuthorId = 0 WHERE AuthorId = ?", (user_id,))
            with suppress(aiosqlite.OperationalError):
                await db.execute("UPDATE WaifuInfo SET ClaimerId = NULL WHERE ClaimerId = ?", (user_id,))
            with suppress(aiosqlite.OperationalError):
                await db.execute("UPDATE WaifuInfo SET Affinity = NULL WHERE Affinity = ?", (user_id,))
            with suppress(aiosqlite.OperationalError):
                await db.execute(
                    """
                    UPDATE WaifuUpdates
                    SET UserId = CASE WHEN UserId = ? THEN 0 ELSE UserId END,
                        OldId = CASE WHEN OldId = ? THEN 0 ELSE OldId END,
                        NewId = CASE WHEN NewId = ? THEN 0 ELSE NewId END
                    WHERE UserId = ? OR OldId = ? OR NewId = ?
                    """,
                    (user_id, user_id, user_id, user_id, user_id, user_id),
                )

            # Delete non-audit state whose ownership is solely this user.
            for table in (
                "UserXpStats",
                "PlantedCurrency",
                "XpShopOwnedItem",
                "BankUsers",
                "UserBetStats",
                "ClubApplicants",
                "ClubBans",
                "ClubInvitations",
                "Rakeback",
                "TimelyCooldown",
                "UserInventory",
                "StockHoldings",
                "SpectatorBets",
                "Stable",
                "StableUnicorn",
            ):
                with suppress(aiosqlite.OperationalError):
                    await db.execute(f"DELETE FROM {table} WHERE UserId = ?", (user_id,))

            # A WaifuInfo row is itself keyed by a Discord user ID. Deleting it
            # also removes dependent WaifuItem rows through the foreign key.
            with suppress(aiosqlite.OperationalError):
                await db.execute("DELETE FROM WaifuInfo WHERE WaifuId = ?", (user_id,))
            with suppress(aiosqlite.OperationalError):
                await db.execute("DELETE FROM DiscordUser WHERE UserId = ?", (user_id,))

            await db.commit()
            log.info(f"Deleted all data for user {user_id}")
