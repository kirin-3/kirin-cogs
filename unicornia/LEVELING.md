# Unicornia Leveling (XP) System

The Unicornia Leveling System is a high-performance experience tracking engine designed to replace Nadeko Bot's XP system. It features message-based and voice-based XP gain, a sophisticated caching strategy to minimize database load, and a fully customizable XP card generator.

## Core Architecture

The system is designed for scale, handling high-traffic servers without blocking the main bot thread.

1.  **System Layer (`systems/xp_system.py`)**: Manages the core logic, including buffering, caching, and background tasks.
2.  **Database Layer (`db/xp.py`)**: Handles persistent storage and complex queries (leaderboards, exclusions).
3.  **Generator Layer (`systems/card_generator.py`)**: specialized module for rendering dynamic images (XP cards).

### XP Flow

1.  **Event**: A user sends a message or joins a voice channel.
2.  **Validation**:
    *   **Global Toggle**: Checks if XP is enabled.
    *   **Cooldown**: Verifies the user isn't on cooldown (default 60s).
    *   **Exclusions**: Checks if the channel or user's role is excluded.
3.  **Calculation**:
    *   XP amount is determined (default 1 per message).
    *   Current XP is fetched from the **LRU Cache**. If missing, it's fetched from the DB.
4.  **Buffering**:
    *   Instead of writing to the DB immediately, the gain is added to an in-memory `xp_buffer`.
5.  **Flushing**:
    *   A background task (`_message_xp_loop`) runs every 30 seconds to bulk-insert all buffered XP into the database in a single transaction.

## Performance Optimization

### 1. Write-Back Buffering
Database writes are the most expensive operation. By buffering XP gains in memory (`self.xp_buffer`) and flushing them in batches, we reduce thousands of potential DB write operations per minute into a single bulk operation.

### 2. LRU Caching
A Least Recently Used (LRU) cache (`self.user_xp_cache`) stores the level stats of active users.
*   **Hits**: If a user chats frequently, their data is served entirely from RAM.
*   **Eviction**: When the cache is full (default 5000 users), the least active users are dropped to free memory.

### 3. Exclusion Caching
Channel and role exclusions are cached (`self.exclusion_cache`) to prevent querying the database on every single message.

## Features

### 1. XP Cards (`[p]level check`)
The system generates dynamic images showing a user's progress.
*   **Custom Backgrounds**: Users can buy backgrounds from the XP Shop (`[p]xpshop`).
*   **Animated GIFs**: Supports animated backgrounds.
*   **Club Integration**: Displays the user's club icon and name.
*   **Font Fallback**: robust handling of special characters (Unicode/Emoji) using fallback fonts (Noto Sans, etc.).

### 2. Voice XP
A background task (`_voice_xp_loop`) awards XP every minute to users in voice channels.
*   **Anti-Abuse**: Users who are self-deafened or server-deafened do not earn XP.
*   **Exclusions**: Honors the same channel/role exclusions as text XP.

### 3. Rewards
*   **Role Rewards**: Automatically assigns roles when a user reaches a specific level. Can also remove roles (e.g., replacing "Novice" with "Expert").
*   **Currency Rewards**: Awards "Slut points" (or configured currency) upon leveling up.

### 4. Customization
Admins can configure:
*   **XP Rate**: Multiplier for global XP gain.
*   **Cooldowns**: Time between valid XP gains.
*   **Exclusions**: Channels or roles that should not earn XP.
*   **Level-Up Messages**: Toggle notifications on/off.

## Database Schema

### `UserXpStats`
Tracks XP per server.
*   `UserId` (Integer, PK)
*   `GuildId` (Integer, PK)
*   `Xp` (Integer): The current XP amount.
*   `AwardedXp` (Integer): Total XP given manually (for auditing).

### `DiscordUser` (Global)
Tracks global total XP (legacy support).
*   `UserId` (Integer, PK)
*   `TotalXp` (Integer)

### `XpSettings`
Server-specific configuration.
*   `GuildId` (Integer, PK)
*   `XpRateMultiplier` (Real)
*   `XpPerMessage` (Integer)

### `XpShopOwnedItem`
Inventory for XP card customizations.
*   `UserId` (Integer)
*   `ItemType` (Integer): 1 = Background.
*   `ItemKey` (String): Unique identifier for the item.
*   `IsUsing` (Boolean): Whether this item is currently equipped.

## Commands

### User
*   `[p]level check [user]`: View level, rank, and XP card.
*   `[p]level leaderboard`: View the server's top users.
*   `[p]xpshop backgrounds`: Browse and buy card backgrounds.

### Admin
*   `[p]unicornia guild xpenabled <true/false>`: Toggle system.
*   `[p]unicornia guild excludechannel <channel>`: Stop XP gain in a channel.
*   `[p]unicornia guild rolereward <level> <role>`: Add a role reward.
*   `[p]unicornia guild currencyreward <level> <amount>`: Add a cash reward.

## Image Generation Details

The `XpCardGenerator` uses **Pillow (PIL)** for rendering.
*   **Async I/O**: Downloads avatars and background images asynchronously using `aiohttp` to prevent blocking the bot.
*   **Thread Execution**: The heavy image processing (compositing, drawing text) runs in a separate thread executor to keep the bot responsive.
*   **SSRF Protection**: Image downloads are validated to prevent Server-Side Request Forgery attacks (e.g., blocking access to local network IPs).

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
Changes to this file can be applied instantly with `[p]xpshop reload`.