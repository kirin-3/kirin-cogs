# Unicornia Economy System

The Unicornia Economy System is a comprehensive currency and transaction management system designed to replicate and enhance the functionality of Nadeko Bot's economy features. It is built as a Python cog for Red-DiscordBot but maintains architectural compatibility with Nadeko's database schema to facilitate seamless migration.

## Core Architecture

The economy system is built on a modular architecture separating data access, business logic, and presentation layers:

1.  **Database Layer (`db/economy.py`)**: Handles all raw SQL interactions with the SQLite database. It uses atomic updates (`UPDATE ... WHERE Balance >= ?`) to ensure data integrity and prevent race conditions.
2.  **System Layer (`systems/economy_system.py`)**: Implements the business logic (e.g., checking cooldowns, calculating interest, logging transactions).
3.  **Command Layer (`commands/economy.py`)**: Defines the user-facing Discord commands and formats output using Embeds.

### Currency Flow

The currency (default name "Slut points") flows through the system via several mechanisms:

*   **Sources (Faucets)**:
    *   **Daily Rewards (`[p]timely`)**: Users claim a daily amount.
        *   **Streak Bonus**: Increases with consecutive daily claims (Caps at 30 days / 300 bonus).
        *   **Supporter Bonus**: Extra currency for users with specific supporter roles.
        *   **Booster Bonus**: Extra currency for Server Boosters.
    *   **Currency Generation**: Random currency spawns in chat channels (`[p]pick`), simulating "flowers" from Nadeko.
    *   **Gambling Wins**: Users can win currency from games like Blackjack, Slots, and Betroll.
    *   **Rakeback**: Users earn back 5% of their gambling losses, claimed via `[p]economy rakeback`.

*   **Sinks**:
    *   **Shop Purchases**: Buying roles, items, XP card backgrounds, or Discord Nitro removes currency from circulation.
    *   **Gambling Losses**: A house edge is built into games to naturally remove currency over time.
    *   **Waifu Gifts**: Gifts increase a waifu's value but cost currency, effectively removing it from the user's wallet.
    *   **Transfer Fees**: Transferring waifus incurs a **10%** (or **60%** if affinity matches) tax.
    *   **Decay**: An automated system to slowly decay balances of wealthy users to control inflation.

## Database Schema

The system uses an SQLite database (`unicornia.db`) with tables mirroring Nadeko Bot v3 structure.

### `DiscordUser`
The central table for user data.
*   `UserId` (Integer, PK): Discord User ID.
*   `CurrencyAmount` (Integer): The user's wallet balance.
*   ... (Other columns for XP, etc.)

### `BankUsers`
Stores separate bank balances.
*   `UserId` (Integer, PK): Discord User ID.
*   `Balance` (Integer): The amount stored in the bank.

### `CurrencyTransactions`
A strict audit log of every balance change.
*   `Id` (Integer, PK, Auto-increment)
*   `UserId` (Integer): The user affected.
*   `Amount` (Integer): The change amount (positive for gain, negative for loss).
*   `Type` (String): The transaction type (e.g., "gift", "shop", "timely").
*   `Reason` (String): Human-readable note.
*   `OtherId` (String): ID of related entity (e.g., sender ID for transfers).
*   `DateAdded` (DateTime): Timestamp.

### `PlantedCurrency`
Stores currently active "pickable" currency on the ground.
*   `Id` (Integer, PK)
*   `GuildId` (Integer)
*   `ChannelId` (Integer)
*   `Amount` (Integer)
*   `Password` (String, Optional): If set, users must type the password to pick.

## Key Features

### 1. Atomic Transactions
To prevent race conditions (e.g., a user spending the same money twice in split-second commands), all balance deductions use **Atomic SQL Updates**:

```sql
UPDATE DiscordUser
SET CurrencyAmount = CurrencyAmount - ?
WHERE UserId = ? AND CurrencyAmount >= ?
```

If the user's balance is insufficient, the `UPDATE` affects 0 rows, and the transaction is aborted at the database level. This is far more secure than a "Read -> Check -> Write" pattern in application code.

### 2. Banking System
Users have a separate "Bank" account. This separation is useful for:
*   Protecting funds from accidental spending.
*   Future implementation of interest systems.
*   Role-playing elements.

### 3. Gambling System
The gambling module integrates deeply with the economy:
*   **Provably Fair RNG**: Uses Python's `secrets` module for cryptographically secure random number generation.
*   **Rakeback**: Tracks total losses per user and accumulates a 5% rebate.
*   **Global Stats**: Tracks `GamblingStats` (global) and `UserBetStats` (per-user) to monitor the economy's health.

**Supported Games:**
*   **Blackjack**: Interactive game with Hit/Stand logic and **2.5x** payout for Natural 21.
*   **Slots**: Multi-line payout logic matching Nadeko's original probability table (Jokers/Triples).
*   **Betroll**: Simple 1-100 roll (Win if 66+). Payout: 2x.
*   **Lucky Ladder**: A high-risk, high-reward game with 8 rungs. Multipliers range from 0.1x to **2.4x**.
*   **Rock Paper Scissors**: PVP against the bot. Win 2x.
*   **Betflip**: Coin flip guess. Payout: **1.95x**.

### 4. Waifu Economy
Waifus act as unique assets that can be traded.
*   **Claiming**: Users can claim others for a price.
*   **Value Growth**: The price of a waifu increases as they are gifted items.
*   **Affinity**: Setting an affinity provides a **20% discount** on claiming that user.
*   **Transfer Logic**: Transferring a waifu incurs a tax, and the waifu's price is *reduced* by the tax amount, resetting their market value slightly.

### 5. Shop System
The shop allows admins to sell:
*   **Roles**: Automatically assigned upon purchase (checks for requirements).
*   **Items**: Added to user inventory.
*   **XP Backgrounds**: Visual customization for the leveling system (`[p]xpshop`).
*   **Nitro Shop**: Buy Discord Nitro Boost or Basic subscriptions.

### 6. Currency Decay
An optional anti-inflation system that decays balances over time.
*   **Configurable**: Admins can set `decay_percent`, `decay_max_amount`, `decay_min_threshold`, and `decay_hour_interval`.
*   **Scope**: Decays both wallet and bank balances if total wealth exceeds the threshold.

## Configuration

Admins can configure the economy via `[p]unicornia config` or by editing `unicornia/xp_config.yml` (for XP shop).

*   `currency_name`: Name of the currency.
*   `currency_symbol`: Emoji/Symbol used in displays.
*   `timely_amount`: Base amount for daily claims.
*   `generation_chance`: Probability of currency spawning in chat (0.0-1.0).
*   `decay_percent`: Percentage of wealth removed per interval.
*   `gambling_min_bet` / `gambling_max_bet`: Betting limits.

## Migration Guide (Nadeko -> Unicornia)

The system automatically detects an existing `nadeko.db` file in the cog folder. On first load, it runs a migration script (`db.migrate_from_nadeko`) that:
1.  Reads user balances from Nadeko's `DiscordUser`.
2.  Transfers Bank balances from `BankUsers`.
3.  Preserves transaction history (where schema permits).
4.  Maps internal Integer IDs to Discord Snowflake IDs to ensure data continuity.

## Security Considerations

*   **Input Validation**: All text inputs (notes, names) are sanitized to prevent formatting exploits.
*   **Positive Integer Enforcement**: All commands enforce `amount > 0` checks.
*   **Bot Exclusion**: Bots cannot hold currency or be traded as waifus.
*   **Transaction Logging**: Every single currency movement is logged to `CurrencyTransactions`, providing a complete audit trail for server admins.
