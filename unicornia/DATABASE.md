# Unicornia Database Documentation

This document explains the database architecture, file location, and migration process for the Unicornia cog.

## Database Location

The Unicornia database is an SQLite database located at:
`unicornia/data/unicornia.db` (Relative to the bot's root directory, inside the cog folder)

This file stores all user data, including XP, currency, clubs, and waifus.

## WAL Mode (Why extra files appear)

Unicornia uses **WAL (Write-Ahead Logging) Mode** for performance and data integrity. This is why you will see two additional files alongside the main database:

*   `unicornia.db` - The main database file.
*   `unicornia.db-shm` - Shared memory file (temporary).
*   `unicornia.db-wal` - Write-ahead log file (temporary).

**Do not delete the -wal or -shm files** while the bot is running, as they contain uncommitted data. They are automatically managed by SQLite.

### Hourly maintenance

Every hour the cog runs a passive WAL checkpoint and `PRAGMA quick_check`. The check reads the whole file, so it runs on its own read-only connection: in WAL mode a reader doesn't block writers, and economy commands keep working while it runs. A failed check is logged as `Database integrity check failed`.

## Migration from Nadeko

Migration is manual, not automatic: point the cog at the source database with `[p]unicornia migration setpath <path>` and run `[p]unicornia migration run`. The migration looks for `nadeko.db` at the configured path, falling back to bot-working-directory locations (`/data/nadeko.db`, `data/nadeko.db`, `nadeko.db`, `data/nadeko/nadeko.db`).

### Migration Process
1.  **Detection**: Reads `nadeko.db` from the configured path (or the fallback locations above).
2.  **Mapping**: Reads data from Nadeko's tables and inserts it into Unicornia's tables.
3.  **ID Translation**:
    *   Nadeko uses internal Integer IDs for linking users (e.g., in Waifu and Club tables).
    *   Unicornia translates these internal IDs to Discord Snowflake IDs (User IDs) by joining with the `DiscordUser` table during migration. This ensures that waifus and clubs are correctly linked to users even though the underlying ID system changed.
4.  **Completion**: Logs "Migration from Nadeko database completed successfully" to the console.

### Migrated Tables
*   `DiscordUser` (Currency, XP, Club Membership)
*   `BankUsers` (Bank Balance)
*   `WaifuInfo`, `WaifuItem`, `WaifuUpdates` (Waifu System)
*   `Clubs`, `ClubApplicants`, `ClubBans` (Club System)
*   `XpSettings`, `XpRoleReward`, `XpExcludedItem` (XP Configuration)
*   `GamblingStats`, `UserBetStats` (Gambling Statistics)
*   `ShopEntry`, `ShopEntryItem` (Shop Items)
*   `XpShopOwnedItem` (XP Card Backgrounds)

## Database Schema

Unicornia uses a schema compatible with Nadeko Bot but optimized for Red.

### Core User Data

#### `DiscordUser`
The central table for user data.
*   `UserId` (Integer, PK): Discord User ID.
*   `Username` (Text): Cached username (for migration/display).
*   `AvatarId` (Text): Cached avatar hash.
*   `ClubId` (Integer): ID of the club the user belongs to.
*   `IsClubAdmin` (Integer): 1 if admin, 0 otherwise.
*   `TotalXp` (Integer): Total global XP.
*   `CurrencyAmount` (Integer): Current wallet balance.

### Economy

#### `BankUsers`
Stores separate bank balances.
*   `UserId` (Integer, PK): Discord User ID.
*   `Balance` (Integer): The amount stored in the bank.

#### `CurrencyTransactions`
A strict audit log of every balance change.
*   `Id` (Integer, PK, Auto-increment)
*   `UserId` (Integer): The user affected.
*   `Type` (Text): Transaction type (e.g., "gift", "shop", "timely").
*   `Amount` (Integer): The change amount.
*   `Reason` (Text): Human-readable note.
*   `OtherId` (Integer): ID of related entity (e.g., sender ID).
*   `Extra` (Text): Additional metadata.
*   `DateAdded` (Text): Timestamp.

#### `Rakeback`
Stores accumulated gambling losses for rakeback.
*   `UserId` (Integer, PK)
*   `RakebackBalance` (Integer): Amount available to claim (5% of losses).

#### `TimelyCooldown`
Tracks daily reward claims.
*   `UserId` (Integer, PK)
*   `LastClaim` (Text): Timestamp of last claim.
*   `Streak` (Integer): Consecutive days claimed.

#### `PlantedCurrency`
Stores currently active "pickable" currency on the ground.
*   `Id` (Integer, PK)
*   `GuildId` (Integer)
*   `ChannelId` (Integer)
*   `UserId` (Integer): Who planted it (if manually dropped).
*   `MessageId` (Integer)
*   `Amount` (Integer)
*   `Password` (Text, Optional): For protected drops.

#### `EconomyOperations`
Idempotent balance operations, keyed by a caller-supplied operation key so retries never repeat a balance effect.
*   `Id` (Integer, PK)
*   `OperationKey` (Text, Unique)
*   `GuildId` (Integer)
*   `UserId` (Integer)
*   `Source` (Text): Calling cog/system identity.
*   `Direction` (Text): "credit" or "debit".
*   `Amount` (Integer)
*   `State` (Text): Operation state.
*   `Result` (Text)
*   `CreatedAt` (Text), `SettledAt` (Text)

#### `YieldPool`
The single-row stock-dividend pool funded by house edge and trade tax.
*   `Id` (Integer, PK, always 1)
*   `Balance` (Integer): Currently distributable.
*   `LifetimeHouseBanked`, `LifetimePooled`, `LifetimeTradeTax` (Integer): Lifetime funding breakdown.
*   `NextDistributionAt` (Text)
*   `UpdatedAt` (Text)

#### `DividendRuns`
One row per completed dividend distribution.
*   `PeriodEnd` (Text, PK)
*   `Distributed` (Integer), `Recipients` (Integer)
*   `CompletedAt` (Text)

#### `DividendPayouts`
Per-user dividend payments by period and symbol.
*   `Id` (Integer, PK)
*   `PeriodEnd` (Text), `UserId` (Integer), `Symbol` (Text)
*   `Weight` (Real): The holder's share weight.
*   `Amount` (Integer)
*   `DateAdded` (Text)

#### `SpectatorMarkets`
Parimutuel spectator markets on live blackjack hands.
*   `Id` (Integer, PK)
*   `HandKey` (Text, Unique)
*   `State` (Text), `Outcome` (Text)
*   `OpenedAt` (Text), `ClosedAt` (Text)

#### `SpectatorBets`
Individual spectator wagers.
*   `Id` (Integer, PK)
*   `MarketId` (Integer, FK to `SpectatorMarkets`)
*   `UserId` (Integer), `Side` (Text), `Amount` (Integer)
*   `StakeKey` (Text, Unique): Idempotency key per wager.

### XP System

#### `UserXpStats`
Tracks XP per server.
*   `UserId` (Integer, PK)
*   `GuildId` (Integer, PK)
*   `Xp` (Integer): The current XP amount.

#### `XpSettings`
XP configuration per guild.
*   `GuildId` (Integer, PK)
*   `XpRateMultiplier` (Real)
*   `XpPerMessage` (Integer)
*   `XpMinutesTimeout` (Integer)

#### `XpRoleReward`
Roles awarded for reaching levels.
*   `Id` (Integer, PK)
*   `GuildId` (Integer)
*   `Level` (Integer)
*   `RoleId` (Integer)
*   `Remove` (Boolean): If true, remove role instead of adding.

#### `XpCurrencyReward`
Currency awarded for reaching levels.
*   `Id` (Integer, PK)
*   `XpSettingsId` (Integer): FK to XpSettings (effectively GuildId).
*   `Level` (Integer)
*   `Amount` (Integer)

#### `XpShopOwnedItem`
Inventory for XP card customizations (Backgrounds).
*   `Id` (Integer, PK)
*   `UserId` (Integer)
*   `ItemType` (Integer): 1 = Background.
*   `ItemKey` (Text): Unique identifier string.
*   `IsUsing` (Boolean): Whether this item is currently equipped.

### Clubs

#### `Clubs`
Stores club information.
*   `Id` (Integer, PK)
*   `Name` (Text, Unique)
*   `Description` (Text)
*   `ImageUrl` (Text)
*   `BannerUrl` (Text)
*   `Xp` (Integer)
*   `OwnerId` (Integer): Discord ID of the owner.
*   `DateAdded` (Text)

#### `ClubApplicants`
Users applying to join clubs.
*   `ClubId` (Integer, PK, FK)
*   `UserId` (Integer, PK)
*   `DateAdded` (Text)

#### `ClubBans`
Users banned from clubs.
*   `ClubId` (Integer, PK, FK)
*   `UserId` (Integer, PK)
*   `DateAdded` (Text)

#### `ClubInvitations`
Pending invitations to users.
*   `ClubId` (Integer, PK, FK)
*   `UserId` (Integer, PK)
*   `DateAdded` (Text)

### Shop System

#### `ShopEntry`
Items available for purchase.
*   `Id` (Integer, PK)
*   `GuildId` (Integer)
*   `Index` (Integer): Display order.
*   `Price` (Integer)
*   `Name` (Text)
*   `AuthorId` (Integer)
*   `Type` (Integer): Role, Item, Effect, etc.
*   `RoleName` (Text)
*   `RoleId` (Integer)
*   `RoleRequirement` (Integer)
*   `Command` (Text): Legacy/Unused.

#### `UserInventory`
Users' purchased shop items.
*   `UserId` (Integer, PK)
*   `GuildId` (Integer, PK)
*   `ShopEntryId` (Integer, PK, FK)
*   `Quantity` (Integer)
*   `DateAdded` (Text)

### Waifu System

#### `WaifuInfo`
Waifu status and value.
*   `WaifuId` (Integer, PK): Discord User ID.
*   `ClaimerId` (Integer): Owner ID.
*   `Affinity` (Integer): User ID they like.
*   `Price` (Integer)
*   `DateAdded` (Text)

#### `WaifuItem`
Gifts given to waifus.
*   `Id` (Integer, PK)
*   `WaifuInfoId` (Integer, FK)
*   `ItemEmoji` (Text)
*   `Name` (Text)
*   `DateAdded` (Text)

#### `WaifuUpdates`
History of claims and transfers.
*   `Id` (Integer, PK)
*   `UserId` (Integer): The waifu.
*   `OldId` (Integer): Previous owner.
*   `NewId` (Integer): New owner.
*   `UpdateType` (Integer): 0=Claim, 1=Divorce, 2=Transfer, 99=Reset.
*   `DateAdded` (Text)

### Gambling Statistics

#### `GamblingStats`
Global gambling stats.
*   `Feature` (Text, PK): Game name.
*   `BetAmount` (Integer)
*   `WinAmount` (Integer)
*   `LossAmount` (Integer)

#### `UserBetStats`
Per-user gambling stats.
*   `Id` (Integer, PK)
*   `UserId` (Integer)
*   `Game` (Text)
*   `BetAmount` (Integer)
*   `WinAmount` (Integer)
*   `LossAmount` (Integer)
*   `MaxWin` (Integer)

### Stock Market

#### `Stocks`
One row per listed stock.
*   `Symbol` (Text, PK), `Name` (Text), `Emoji` (Text)
*   `CurrentPrice`, `PreviousPrice` (Integer)
*   `TotalShares` (Integer), `ShareReserve` (Real)
*   `SmoothedUsage` (Real), `PeriodUsage` (Integer), `Volatility` (Real)
*   `Hidden` (Integer): 1 if delisted from listings.

#### `StockHoldings`
Shares held per user and symbol.
*   `UserId` (Integer, PK), `Symbol` (Text, PK, FK to `Stocks`)
*   `Amount` (Integer), `AverageCost` (Real)

#### `StockTransactions`
Every buy and sell.
*   `Id` (Integer, PK)
*   `UserId` (Integer), `Symbol` (Text)
*   `Side` (Text): "buy" or "sell".
*   `Kind` (Text): "trade" or an import marker.
*   `Shares` (Integer), `ExecPrice` (Real), `Tax` (Integer), `TotalAmount` (Integer)
*   `IsImported` (Integer), `DateAdded` (Text)

### Configuration

#### `BotConfig`
Persistent system configuration.
*   `Key` (Text, PK)
*   `Value` (Text)
*   `Description` (Text)

#### `Event`
Currency generation events in progress (matching Nadeko's Event).
*   `Id` (Integer, PK)
*   `GuildId` (Integer), `ChannelId` (Integer), `Event` (Text)

#### `GCChannelId`
Channels where currency generation is enabled.
*   `Id` (Integer, PK)
*   `GuildId` (Integer)
*   `ChannelId` (Integer)
