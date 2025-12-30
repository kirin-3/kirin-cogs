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

## Migration from Nadeko

When the cog loads, it attempts to migrate data from an existing Nadeko Bot database (`nadeko.db`) if found in the cog's directory.

### Migration Process
1.  **Detection**: Checks for `nadeko.db` in the `unicornia/` folder.
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

## Database Schema

Unicornia creates tables that match Nadeko's schema naming convention to ensure compatibility:

*   `DiscordUser`: Core user data.
*   `BankUsers`: Bank balances.
*   `CurrencyTransactions`: Transaction history.
*   `Clubs`: Club information.
*   `WaifuInfo`: Waifu claims and affinity.
*   `WaifuItem`: Waifu gifts/inventory.
*   `WaifuUpdates`: Waifu transaction history.

Note: The `InterestRate` column was removed from `BankUsers` as it is not used in the current version of Nadeko.