# Unicornia - Full-Featured Leveling and Economy Cog

A complete Red bot cog that provides comprehensive leveling and economy features similar to Nadeko. Built with a modular architecture for better maintainability and extensibility.

## Features

### Core Systems
- **Level System**: Automatic XP gain from messages with level up rewards
- **Economy System**: Complete currency system with wallet and bank
- **Gambling System**: Multiple gambling games with visual feedback
- **Currency Generation**: Random currency spawning in messages with password protection
- **Currency Decay**: Automatic currency decay over time to prevent inflation

### Leveling Features
- **XP Gain**: Configurable XP per message with cooldowns
- **Level Up Rewards**: Role and currency rewards for reaching levels
- **Channel Exclusions**: Exclude specific channels or roles from XP gain
- **Voice XP**: XP gain from voice channel participation (planned)
- **XP Banners**: Personal XP cards with user avatars (planned)

### Economy Features
- **Wallet & Bank**: Separate wallet and bank account system
- **Currency Transactions**: Full transaction logging and history
- **Daily Rewards**: Timely/daily currency rewards with cooldowns
- **Currency Transfer**: Give currency to other users
- **Admin Tools**: Award/take currency (owner only)

### Gambling Games
- **Betroll**: Dice rolling with multiple multiplier tiers
- **Rock Paper Scissors**: Classic RPS with optional betting
- **Slots**: Slot machine with visual results
- **Lucky Ladder**: 8-rung ladder with different multipliers
- **Blackjack**: Card game (planned)
- **Connect4**: Board game (planned)

### Currency Systems
- **Plant & Pick**: Currency farming with password protection
- **Currency Decay**: Automatic decay to prevent inflation
- **Generation Events**: Random currency spawning in messages
- **Transaction Logging**: Complete audit trail of all currency movements

### Configuration
- **Global Settings**: Configure all systems globally
- **Guild Settings**: Per-guild configuration for XP and rewards
- **Role Rewards**: Set roles for specific levels
- **Currency Rewards**: Set currency amounts for level ups
- **Channel Management**: Include/exclude channels from XP gain

## Installation

1. Place the `unicornia` folder in your Red bot's `cogs` directory
2. Install the required dependency: `pip install aiosqlite`
3. Load the cog: `[p]load unicornia`

## Configuration

Before using the cog, you need to configure the path to your Nadeko database:

```
[p]unicornia config nadeko_db_path /path/to/your/NadekoBot.db
```

### Available Settings

- `nadeko_db_path`: Path to your Nadeko SQLite database file
- `currency_name`: Name of the currency (default: "Nadeko Coins")
- `currency_symbol`: Symbol for the currency (default: "N")
- `xp_enabled`: Enable/disable XP system (default: true)
- `economy_enabled`: Enable/disable economy system (default: true)

## Commands

### General Commands

- `[p]unicornia status` - Check cog status and configuration
- `[p]unicornia config <setting> <value>` - Configure global settings (owner only)
- `[p]unicornia guild <setting> <value>` - Configure guild settings (admin only)

### Level Commands

- `[p]level check [user]` - Check your or another user's level and XP
- `[p]level leaderboard [limit]` - Show XP leaderboard for the server

### Economy Commands

- `[p]economy balance [user]` - Check wallet and bank balance
- `[p]economy give <amount> <user> [note]` - Give currency to another user
- `[p]economy timely` - Claim daily currency reward
- `[p]economy award <amount> <user> [note]` - Award currency to user (owner only)
- `[p]economy take <amount> <user> [note]` - Take currency from user (owner only)
- `[p]economy leaderboard [limit]` - Show currency leaderboard

### Bank Commands

- `[p]bank deposit <amount>` - Deposit currency into bank
- `[p]bank withdraw <amount>` - Withdraw currency from bank
- `[p]bank balance` - Check bank balance

### Gambling Commands

- `[p]gambling betroll <amount>` - Bet on a dice roll (1-100)
- `[p]gambling rps <choice> [amount]` - Play rock paper scissors
- `[p]gambling slots <amount>` - Play slots
- `[p]gambling luckyladder <amount>` - Play lucky ladder

### Currency Generation Commands

- `[p]currency pick <password>` - Pick up a currency plant with password

### Configuration Commands

- `[p]unicornia guild xpenabled <true/false>` - Enable/disable XP for guild
- `[p]unicornia guild levelupmessages <true/false>` - Enable/disable level up messages
- `[p]unicornia guild levelupchannel [channel]` - Set level up message channel
- `[p]unicornia guild excludechannel <channel>` - Exclude channel from XP
- `[p]unicornia guild includechannel <channel>` - Include channel in XP
- `[p]unicornia guild rolereward <level> <role>` - Set role reward for level
- `[p]unicornia guild currencyreward <level> <amount>` - Set currency reward for level

## Configuration

### Global Settings (Owner Only)

- `currency_name`: Name of the currency (default: "Unicorn Coins")
- `currency_symbol`: Symbol for the currency (default: "🦄")
- `xp_enabled`: Enable/disable XP system globally (default: true)
- `economy_enabled`: Enable/disable economy system globally (default: true)
- `gambling_enabled`: Enable/disable gambling globally (default: true)
- `shop_enabled`: Enable/disable shop globally (default: true)
- `timely_amount`: Daily reward amount (default: 100)
- `timely_cooldown`: Daily reward cooldown in hours (default: 24)
- `xp_per_message`: XP gained per message (default: 1)
- `xp_cooldown`: XP cooldown in seconds (default: 60)

### Guild Settings (Admin Only)

- `xp_enabled`: Enable/disable XP for this guild
- `level_up_messages`: Enable/disable level up messages
- `level_up_channel`: Channel for level up messages
- `excluded_channels`: Channels excluded from XP gain
- `excluded_roles`: Roles excluded from XP gain
- `role_rewards`: Role rewards for reaching levels
- `currency_rewards`: Currency rewards for reaching levels

## Database Structure

This cog uses its own SQLite database with WAL (Write-Ahead Logging) mode enabled for optimal performance and corruption prevention. The database structure matches Nadeko's schema for easy migration and includes the following tables:

- `DiscordUser`: User data including wallet currency and total XP (matches Nadeko)
- `UserXpStats`: Per-guild user XP data (matches Nadeko)
- `BankUsers`: User bank balances (matches Nadeko)
- `PlantedCurrency`: Currency generation plants (matches Nadeko)
- `ShopEntry`: Shop entries for guilds (matches Nadeko)
- `ShopEntryItem`: Items within shop entries (matches Nadeko)
- `XpCurrencyReward`: Currency rewards for reaching levels (matches Nadeko)
- `GCChannelId`: Currency generation channels (matches Nadeko)
- `currency_transactions`: Currency transaction history
- `timely_claims`: Daily reward claim tracking
- `shop_items`: Shop items
- `user_shop_items`: User's purchased items
- `waifus`: Waifu system data
- `waifu_items`: Waifu items and gifts
- `waifu_updates`: Waifu system transaction history
- `xp_shop_items`: XP shop customization items

### Migration from Nadeko

The cog automatically migrates data from an existing Nadeko database on first load. Place your Nadeko database file at `data/nadeko.db` and the cog will automatically import:

- ✅ User wallet currency (`CurrencyAmount`)
- ✅ User total XP (`TotalXp`) 
- ✅ Per-guild XP (`UserXpStats`)
- ✅ Bank balances (`BankUsers`)
- ✅ Currency plants (`PlantedCurrency`)
- ✅ Shop entries (`ShopEntry` and `ShopEntryItem`)
- ✅ XP currency rewards (`XpCurrencyReward`)
- ✅ Currency generation channels (`GCChannelId`)
- ✅ User usernames and avatars

### Database Optimizations
- **WAL Mode**: Prevents database corruption and improves concurrency
- **Memory Mapping**: 256MB memory mapping for faster access
- **Incremental Vacuum**: Automatic database maintenance
- **Optimized Page Size**: 4KB pages for better performance
- **Automatic Integrity Checks**: Hourly database integrity verification

## Level Calculation

The cog uses Nadeko's exact level calculation formula:

```
Level = (-7/2) + (1/6) * sqrt(8 * total_xp + 441)
Required XP for next level = 9 * (level + 1) + 27
```

## Requirements

- Python 3.8+
- Red bot 3.5.0+
- aiosqlite library

## Features in Detail

### XP System
- Automatic XP gain from messages (configurable amount and cooldown)
- Level up notifications with customizable channel
- Role rewards for reaching specific levels
- Currency rewards for reaching specific levels
- Channel and role exclusions
- Per-guild XP tracking

### Economy System
- Wallet and bank system
- Currency transactions with full logging
- Daily/timely rewards
- Give/take/award commands
- Leaderboards

### Gambling System
- Betroll (dice betting)
- Rock Paper Scissors
- Configurable payouts
- Transaction logging

### Banking System
- Deposit/withdraw currency
- Separate bank balance tracking
- Transaction logging

## Notes

- This cog creates and manages its own database
- All user data is stored locally in SQLite
- Fully configurable for different guilds
- Compatible with Red bot's permission system

## Support

If you encounter any issues, please check:

1. The database path is correct and accessible
2. The Nadeko database file exists and is not corrupted
3. You have the required permissions to read the database file
4. The aiosqlite library is installed

## License

This cog is provided as-is for migration purposes from Nadeko to Red bot.
