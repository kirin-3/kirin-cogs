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
    *   **Cooldown**: Verifies the user isn't on cooldown (Default: 180s, Configurable).
    *   **Whitelist Check**: **Critical**: XP is **Whitelist Only**. The channel (or its parent Category/Thread) MUST be in the `xp_included_channels` list.
    *   **Role Exclusion**: Checks if the user has any excluded roles.
3.  **Calculation**:
    *   XP amount is determined (Default: 3 per message, Configurable).
    *   Effective XP is committed guild XP plus accepted message gains still waiting to be persisted. The **LRU Cache** stores this combined total. On a cache miss, it is rebuilt from the database plus that member's pending gains.
    *   Message cooldown admission is checked again under the XP state lock, so concurrent messages cannot both claim the same cooldown window.
4.  **Buffering**:
    *   Instead of writing to the DB immediately, the gain is added to an in-memory `xp_buffer`.
    *   XP, cache, and cooldown state are recorded before rewards and notifications run. Failed Discord delivery does not discard the gain or replay its level transition.
5.  **Flushing**:
    *   A background task (`_message_xp_loop`) runs every 30 seconds to bulk-insert all buffered XP into the database in a single transaction.
    *   Pending entries remain visible until the transaction commits. A successful flush removes them without adding them to cached totals a second time. A failed transaction rolls back and retains the pending gains for retry.

### Consistent XP Reads and Writes

Message gains, voice awards, owner awards, cache changes, flushes, and level-stat reads share an XP state lock. Voice and owner awards invalidate affected cache entries after a successful commit, so the next message uses their updated XP. The database transaction updates guild XP and global total XP together; a partial failure rolls both back. Cancelling an active write waits for its outcome and cache/buffer bookkeeping before releasing the lock.

`[p]xp`, `[p]level`, and `[p]level check` include pending message XP without forcing a database flush. For example, moving from 197 to 198 XP announces level 4, and an immediate card also shows level 4. Rank and XP leaderboard queries still use persisted data and can lag pending gains until the next flush.

Discord notifications, role changes, reward delivery, and card rendering run outside the state lock. A notification describes the level reached by its message; further gains while Discord is delivering it can legitimately make a later card higher. The in-memory buffer is not durable across abrupt process termination.

### Reload and Shutdown

Cog unload stops new XP admission, cancels and awaits XP loops, drains in-flight writes and level-up callbacks, and flushes remaining message gains before closing the database. XP shutdown runs before other systems' cleanup, so their failures cannot leave XP loops active. Concurrent shutdown callers share one drain operation, and cancelling a caller waits for it to complete. A replacement XP system starts with an empty cache and reads the persisted totals. If the final flush fails, the failure is logged; pending gains cannot be guaranteed across shutdown with unavailable storage.

When first upgrading from the version with the stale-cache bug, allow a normal buffer flush and restart the bot. The old version's already-loaded unload handler does not stop its XP loops. Once this fix is loaded, subsequent cog reloads use the corrected shutdown path.

## Performance Optimization

### 1. Write-Back Buffering
Database writes are the most expensive operation. By buffering XP gains in memory (`self.xp_buffer`) and flushing them in batches every 30 seconds, we reduce thousands of potential DB write operations per minute into a single bulk operation.

### 2. LRU Caching
A Least Recently Used (LRU) cache (`self.user_xp_cache`) stores the level stats of active users.
*   **Hits**: If a user chats frequently, their data is served entirely from RAM.
*   **Eviction**: When the cache is full (default 5000 users), the least active users are dropped to free memory.
*   **Invalidation**: Successful voice and owner awards discard only affected user/guild entries. Pending message gains remain in the buffer when an entry is invalidated or evicted.
*   **Thresholds**: The cache compares cumulative XP against the cumulative next-level threshold (198 XP for level 4). Card progress still uses the per-level cost (63 XP from level 3 to level 4); the level formula is unchanged.

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
*   **Triggers**: Rewards and notifications continue to run for message-driven level increases. Voice and owner awards do not introduce announcements or replay rewards for previously crossed levels.

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
*   `[p]level check [user]` (Alias: `[p]level`, `[p]me`): View level, rank, and XP card.
*   `[p]xp [user]`: Global shortcut for checking XP.
*   `[p]level leaderboard` (Alias: `[p]lb`, `[p]top`): View the server's top users.
*   `[p]xplb`: Global shortcut for XP leaderboard.
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
