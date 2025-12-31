# Unicornia Leveling (XP) System

The Unicornia Leveling System is a high-performance experience tracking engine designed to replace Nadeko Bot's XP system. It features message-based and voice-based XP gain, a sophisticated caching strategy to minimize database load, and a fully customizable XP card generator.

## Core Architecture

The system is designed for scale, handling high-traffic servers without blocking the main bot thread.

1.  **System Layer (`systems/xp_system.py`)**: Manages the core logic, including buffering, caching, and background tasks.
2.  **Database Layer (`db/xp.py`, `db/core.py`)**: Handles persistent storage, schema management, and complex queries (leaderboards, rank calculation).
3.  **Generator Layer (`systems/card_generator.py`)**: specialized module for rendering dynamic images (XP cards) using `Pillow`.

### XP Flow

1.  **Event**: A user sends a message or joins a voice channel.
2.  **Validation**:
    *   **Global Toggle**: Checks if XP is enabled via global config.
    *   **Cooldown**: Verifies the user isn't on cooldown (Default: 60s, Configurable).
    *   **Whitelist Check**: **Critical**: XP is **Whitelist Only**. The channel (or its parent Category/Thread) MUST be in the `xp_included_channels` list.
    *   **Role Exclusion**: Checks if the user has any excluded roles.
3.  **Calculation**:
    *   XP amount is determined (Default: 3 per message, Configurable).
    *   Current XP is fetched from the **LRU Cache**. If missing, it's fetched from the DB and cached.
4.  **Buffering**:
    *   Instead of writing to the DB immediately, the gain is added to an in-memory `xp_buffer`.
5.  **Flushing**:
    *   A background task (`_message_xp_loop`) runs every 30 seconds to bulk-insert all buffered XP into the database in a single transaction.

## Performance Optimization

### 1. Write-Back Buffering
Database writes are the most expensive operation. By buffering XP gains in memory (`self.xp_buffer`) and flushing them in batches every 30 seconds, we reduce thousands of potential DB write operations per minute into a single bulk operation.

### 2. LRU Caching
A Least Recently Used (LRU) cache (`self.user_xp_cache`) stores the level stats of active users.
*   **Hits**: If a user chats frequently, their data is served entirely from RAM.
*   **Eviction**: When the cache is full (default 5000 users), the least active users are dropped to free memory.

### 3. Config Caching
Configuration values (rates, enabled status) and Guild settings (whitelisted channels, excluded roles) are cached to prevent querying the config/database on every single message.

## Features

### 1. XP Cards (`[p]level check`)
The system generates dynamic images showing a user's progress.
*   **Custom Backgrounds**: Users can buy backgrounds from the XP Shop (`[p]xpshop`).
*   **Animated GIFs**: Supports animated backgrounds (rendering frame-by-frame).
*   **Club Integration**: Displays the user's club icon and name if they belong to one.
*   **Font Fallback**: robust handling of special characters (Unicode/Emoji) using fallback fonts (Noto Sans, DejaVu, etc.).
*   **Progress Bar**: Visual skewed bar indicating progress to next level.

### 2. Voice XP
A background task (`_voice_xp_loop`) awards XP every minute to users in voice channels.
*   **Rate**: 1 XP per minute.
*   **Anti-Abuse**: Users who are self-deafened or server-deafened do not earn XP.
*   **Exclusions**: Honors the same channel whitelist and role exclusions as text XP.

### 3. Rewards
*   **Role Rewards**: Automatically assigns roles when a user reaches a specific level. Can also remove roles (e.g., replacing "Novice" with "Expert").
*   **Currency Rewards**: Awards currency (e.g., "Slut points") upon leveling up.

## Database Schema

### `UserXpStats`
Tracks XP per server.
*   `UserId` (Integer, PK)
*   `GuildId` (Integer, PK)
*   `Xp` (Integer): The current XP amount.

### `DiscordUser` (Global)
Tracks global total XP (legacy support/migration).
*   `UserId` (Integer, PK)
*   `TotalXp` (Integer)

### `XpRoleReward`
*   `GuildId`
*   `Level`
*   `RoleId`
*   `Remove` (Boolean)

### `XpShopOwnedItem`
Inventory for XP card customizations.
*   `UserId`
*   `ItemType`: 1 = Background.
*   `ItemKey`: Unique identifier string.
*   `IsUsing`: Whether this item is currently equipped.

## Commands

### User
*   `[p]level check [user]` (Alias: `[p]level`): View level, rank, and XP card.
*   `[p]level leaderboard` (Alias: `[p]xplb`): View the server's top users.
*   `[p]xpshop backgrounds`: Browse and buy card backgrounds.
*   `[p]xpshop buy <key>`: Purchase a background.
*   `[p]xpshop use <key>`: Equip a background.
*   `[p]xpshop owned`: View your inventory.

### Admin (Configuration)
#### Global Settings (Owner)
*   `[p]unicornia config xp_enabled <true/false>`: Global toggle.
*   `[p]unicornia config xp_per_message <int>`: XP per message (Default: 3).
*   `[p]unicornia config xp_cooldown <seconds>`: Cooldown between gains (Default: 180).

#### Guild Settings (Admin)
*   `[p]unicornia guild xp include <channel>`: **REQUIRED**. Add channel to whitelist.
*   `[p]unicornia guild xp exclude <channel>`: Remove channel from whitelist.
*   `[p]unicornia guild xp listchannels`: View whitelisted channels.
*   `[p]unicornia guild rolereward <level> <role> [remove]`: Add role reward.
*   `[p]unicornia guild currencyreward <level> <amount>`: Add cash reward.
*   `[p]unicornia guild listrolerewards`: View role rewards.
*   `[p]unicornia guild listcurrencyrewards`: View currency rewards.

## Image Generation Details

The `XpCardGenerator` uses **Pillow (PIL)** for rendering.
*   **Async I/O**: Downloads avatars and background images asynchronously using `aiohttp`.
*   **Thread Execution**: The heavy image processing (compositing, text drawing) runs in a separate thread executor to prevent blocking the bot's event loop.
*   **SSRF Protection**: Image downloads are validated to prevent Server-Side Request Forgery attacks.
*   **Local Caching**: Downloaded images are cached in memory (LRU) to reduce bandwidth.
*   **Animated Support**: Deconstructs GIFs into frames, applies overlay to each frame, and reconstructs the GIF.

## Configuration Files

XP Shop backgrounds are configured in `unicornia/xp_config.yml`.
```yaml
shop:
  bgs:
    default:
      name: "Default"
      price: 0
      url: "https://..."
    custom_bg:
      name: "Cool Background"
      price: 1000
      url: "https://..."
      hidden: false
```
Changes to this file can be applied instantly with `[p]xpshop reload` (Owner only).
