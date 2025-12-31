# Unicornia Waifu System

The Unicornia Waifu System is a trading game where users can "claim" each other as waifus, gift them items to change their value, and trade them for profit. It is designed to be a direct successor to Nadeko Bot's waifu system.

## Core Mechanics

### 1. Claiming
*   **Base Price**: Every unclaimed user starts with a price of **50** Slut points.
*   **Buying**: To claim a user, you must pay their current price.
*   **Force Claim**: You can claim a waifu owned by someone else by paying **120%** of their current price. The previous owner receives this payment.

### 2. Affinity
Users can set an "affinity" towards another user (`[p]waifu affinity @user`). This signifies a special interest or relationship.
*   **Discount**: If you claim a user who has set their affinity to you, you get a **20% discount** on the price.
*   **Lock-in**: While affinity makes claiming easier, it makes transferring harder (see Taxes).

### 3. Gifts and Value
You can increase (or decrease) a waifu's market value by giving them gifts (`[p]waifu gift`).
*   **Value Calculation**: Gifts increase the waifu's price by roughly **90%** of the gift's cost. Some items (like "Potato") decrease the value.
*   **Inventory**: Gifts are stored in the waifu's inventory and are permanent additions to their value profile.

### 4. Transfer & Taxes
You can transfer ownership of a waifu to another user (`[p]waifu transfer`).
*   **No Tax**: Transfers are free. There is no fee or price reduction.

### 5. Divorce and Reset
*   **Divorce**: You can free a waifu you own (`[p]waifu divorce`). They become unclaimed, but their price remains.
*   **Reset**: Admins can completely reset a waifu (`[p]waifu reset`), making them unclaimed and resetting their price to 50.

## Commands

### General
*   `[p]waifu claim <user> [price]`: Claim a user.
*   `[p]waifu transfer <waifu> <new_owner>`: Transfer ownership.
*   `[p]waifu divorce <waifu>`: Release a waifu.
*   `[p]waifu info [user]`: View price, owner, and gifts.
*   `[p]waifu list [user]`: View waifus owned by a user.
*   `[p]waifu leaderboard`: Top waifus by price.
*   `[p]waifu affinity [user]`: Set your affinity.

### Gifting
*   `[p]waifu gift <item> <user>`: Give an item.
*   `[p]gifts`: List all available gifts and their prices.

### Admin / Owner
*   `[p]waifu reset <user>`: Reset a user's waifu status.
*   `[p]waifu price <user> <price>`: Manually set a waifu's price.

## Database Schema

### `WaifuInfo`
Stores current state.
*   `WaifuId` (Integer, PK): Discord User ID of the waifu.
*   `ClaimerId` (Integer): Discord User ID of the owner.
*   `Price` (Integer): Current market value.
*   `Affinity` (Integer): User ID they have affinity for.

### `WaifuItem`
Stores gifts received.
*   `WaifuInfoId` (Integer): ID of the waifu.
*   `Name` (String): Item name (e.g., "Rose").
*   `ItemEmoji` (String): Emoji for display.

### `WaifuUpdates`
Transaction log.
*   `UserId` (Integer): The waifu involved.
*   `OldId` (Integer): Previous owner.
*   `NewId` (Integer): New owner.
*   `UpdateType` (Integer): 0=Claim, 1=Divorce, 2=Transfer, 99=Reset.
