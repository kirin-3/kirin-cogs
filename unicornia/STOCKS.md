# Unicornia Stock Exchange (USE)

The **Unicornia Stock Exchange** is a dynamic, server-wide stock market system fully integrated into the Unicornia economy. It allows users to trade stocks based on server emojis, with prices driven by real-time chat activity and market events.

---

## 📈 Concept

The market simulates a living economy where:
*   **Stocks** represent concepts or entities tied to specific Emojis (e.g., `:rocket:`, `:joy:`).
*   **Demand** is measured by how often these emojis are used in chat.
*   **Supply/Price** is influenced by user trading (Buying/Selling).

The system is designed to be **passive yet engaging**:
*   Users "pump" their bags by using the associated emoji in conversations.
*   Market prices update every hour ("Tick").
*   Random events (Crashes, Bull Runs) keep the market unpredictable.

---

## ⚙️ Mechanics

### 1. Emoji Tracking
The bot monitors every message sent in the server. It counts occurrences of emojis linked to active stocks.
*   **Logic**: If "ROCKET" stock is tied to `🚀`, every use of `🚀` increases the stock's "Usage Score".
*   **Performance**: Uses efficient Regex parsing and in-memory buffering. No database writes occur per-message.

### 2. Price Movement (The Tick)
Every hour, the **Market Tick** processes the accumulated usage data:
*   **Growth**: Prices increase based on usage volume relative to volatility.
*   **Decay**: All stocks suffer a small natural decay (2%) to prevent infinite inflation if unused.
*   **Formula**: `NewPrice = CurrentPrice * (1 + Growth - Decay + RandomNoise)`

### 3. Market Events
Each tick has a **5% chance** to trigger a global event:
*   **🐂 Bull Run**: All prices skyrocket by **30%**.
*   **📉 Market Crash**: All prices plummet by **30%**.

### 4. Trading & Slippage
Users can Buy and Sell stocks using their Unicornia currency (Slut points).
To simulate real market liquidity, **Slippage** is applied:
*   **Buying** drives the price **UP**.
*   **Selling** drives the price **DOWN**.
*   **Impact**: 0.05% per share traded.
    *   *Example*: Buying 1,000 shares increases the price by 50% immediately. This prevents infinite arbitrage and encourages strategic small trades.

---

## 🎮 Commands

### User Commands
| Command | Alias | Description |
| :--- | :--- | :--- |
| `[p]stock list` | `all` | View all active stocks and current prices. |
| `[p]stock buy <ticker> <amount>` | | Buy shares. Requires currency in wallet. |
| `[p]stock sell <ticker> <amount>` | | Sell shares. Proceeds go to wallet. |
| `[p]stock portfolio` | `holdings` | View your owned stocks and Profit/Loss. |

### Admin Commands
| Command | Permission | Description |
| :--- | :--- | :--- |
| `[p]stock ipo <symbol> <price> <emoji> <name>` | Owner | Launch a new stock. |
| `[p]stock delist <symbol>` | Owner | Remove a stock permanently. |
| `[p]stock dashboard [channel]` | Admin | Create a real-time auto-updating market board. |

---

## 🚀 Setup Guide

### Step 1: Launch Stocks (IPO)
Use the `ipo` command to create the initial market.
```
[p]stock ipo ROCKET 100 🚀 "Moon Rocket Inc."
[p]stock ipo PEPE 50 <:pepe:123456789> "Rare Pepes"
```
*   **Symbol**: Short ticker (e.g., ROCKET).
*   **Price**: Starting price.
*   **Emoji**: The emoji to track (Unicode or Custom).
*   **Name**: Full display name.

### Step 2: Create Dashboard
Create a dedicated channel (e.g., `#stock-market`) and post the dashboard.
```
[p]stock dashboard #stock-market
```
The bot will post an embed with **Interactive Buttons** (Buy, Sell, Portfolio) that allow users to trade without typing commands. This message updates automatically every hour.

---

## 🛠️ Technical Architecture

### System Components
*   **`MarketSystem`** (`systems/market_system.py`): The core engine. Handles the hourly loop (`market_tick`), thread-safe locking, and emoji processing.
*   **`StockRepository`** (`db/stock.py`): Manages SQLite tables `Stocks` and `StockHoldings`.
*   **`StockCommands`** (`commands/stock.py`): Discord interface.
*   **`StockDashboardView`** (`market_views.py`): Persistent UI view handling button interactions.

### Database Schema
**Table `Stocks`**:
*   `Symbol` (PK): Ticker.
*   `CurrentPrice`, `PreviousPrice`: Price tracking.
*   `TotalShares`: Global volume.
*   `Volatility`: Multiplier for price swings (Default 1.0).

**Table `StockHoldings`**:
*   `UserId`, `Symbol`: Composite PK.
*   `Amount`: Shares owned.
*   `AverageCost`: Cost basis for P/L calculation.

### Safety Features
*   **Async Locking**: Prevents race conditions between hourly ticks and user trades.
*   **Transaction Limits**: Max 100,000 shares per trade.
*   **Input Validation**: Strict type checking and negative number prevention.
