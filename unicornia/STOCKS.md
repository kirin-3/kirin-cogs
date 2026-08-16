# Unicornia Stock Exchange (USE)

The **Unicornia Stock Exchange** is a dynamic, server-wide stock market system fully integrated into the Unicornia economy. It allows users to trade stocks based on server emojis, with prices driven by real-time chat activity and market events.

---

## 📈 Concept

The market simulates a living economy where:
*   **Stocks** represent concepts or entities tied to specific Emojis (e.g., `:rocket:`, `:joy:`).
*   **Demand** is measured by how often these emojis are used in chat.
*   **Price** follows relative emoji activity and is also moved by buying and selling along a bounded curve.

The system is designed to be **passive yet engaging**:
*   Users "pump" their bags by using the associated emoji in conversations.
*   Market prices update every hour ("Tick").
*   Occasional market events create temporary shocks that fade as prices return toward fair value.

---

## ⚙️ Mechanics

### 1. Emoji Tracking
The bot monitors every message sent in the server. It counts occurrences of emojis linked to active stocks.
*   **Logic**: If "ROCKET" stock is tied to `🚀`, every use of `🚀` increases the stock's "Usage Score".
*   **Performance**: Uses efficient Regex parsing and in-memory buffering. No database writes occur per-message.

### 2. Price Movement (The Tick)
Every hour, the **Market Tick** processes the accumulated usage data:
*   Each stock keeps an exponential moving average of its usage: `smoothed = 0.9 × old + 0.1 × current`.
*   Fair value depends on the stock's share of market-wide smoothed usage, not its raw count. Scaling every emoji's usage equally therefore leaves prices unchanged.
*   A proportional floor keeps unused stocks from collapsing: `w = (smoothed + 0.5 × total / N) / (1.5 × total)`. When total usage is zero, every stock receives `w = 1/N`.
*   Fair value is `100 × (w × N)^0.7`.
*   Price mean-reverts in log space: `log(price) += 0.08 × (log(fair) − log(price)) + 0.02 × noise`.
*   A single hourly tick is limited to a 15% log move, and prices remain between 1 and 1,000,000.

Prices are stored with their fractional precision. Commands and dashboards round them to two decimal places only for display.

### 3. Market Events
Each tick has a **2% chance** to trigger a global event:
*   **🐂 Bull Run**: a temporary **+12%** shock.
*   **📉 Market Crash**: a temporary **−12%** shock.

The regular movement clamp still applies, and mean reversion pulls prices back toward fair value afterward.

### 4. Trading & Slippage
Users can Buy and Sell stocks using their Unicornia currency (Slut points).
To simulate real market liquidity, each stock has a mutable **share reserve** initially set to 100,000 shares:
*   **Buying** drives the price **UP**.
*   **Selling** drives the price **DOWN**.
*   A buy removes shares from the reserve; a sell returns them. The next share receives a worse rate than the previous one, so larger orders have increasing impact.
*   The displayed execution rate is the average along the entire curve, not the starting or ending quote.
*   One trade cannot move price outside the configured impact band of 0.9× through 1/0.9×. At the initial reserve, the largest buy is 10,000 shares and moves spot about +11.11%.
*   Sell limits are calculated against the post-sale reserve, allowing even a maximum-size buy to be sold back immediately.
*   Buying and immediately selling the same quantity restores both price and reserve exactly before fees. The trader loses only the 1% tax charged on each leg.

Splitting an order does not avoid curve cost: the closed-form path integral produces the same gross total across consecutive pieces, apart from whole-currency rounding and taxes.

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
| `[p]stock unwind` | Owner | Preview a cost-basis refund and full market reset. Dry-run by default. |
| `[p]stock unwind confirm` | Owner | Execute the previously previewed unwind after validating every holding. |
| `[p]stock dashboard [channel]` | Admin | Create a real-time auto-updating market board. |

### Owner-only position unwind

`[p]stock unwind` reports how many users and holdings would be affected, the total currency refund, and any holding whose purchase cost cannot be reconstructed. It changes nothing.

`[p]stock unwind confirm` refunds each remaining position at its recorded average purchase cost, records both currency and stock-ledger audit rows, removes all holdings, and resets prices to 100 with the initial share reserve. It does not use current market prices and does not claw back gains from shares already sold.

The confirmed operation fails closed if even one holding lacks a resolvable cost basis: no run identifier is created and no balance, holding, reserve, or price changes. Repair every position named by the dry-run report before confirming. Refund keys are persisted per run, so an interrupted operation resumes without paying any holding twice.

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
*   `ShareReserve`: Mutable pricing reserve (Default 100,000).
*   `SmoothedUsage`: Persisted emoji-usage EMA.
*   `Volatility`: Multiplier for price swings (Default 1.0).

**Table `StockHoldings`**:
*   `UserId`, `Symbol`: Composite PK.
*   `Amount`: Shares owned.
*   `AverageCost`: Cost basis for P/L calculation.

### Safety Features
*   **Async Locking**: Prevents race conditions between hourly ticks and user trades.
*   **Impact Limits**: Per-side share caps keep every trade inside the configured price-impact band.
*   **Fail-closed Unwind**: Confirmation aborts before any mutation if a cost basis cannot be resolved.
*   **Idempotent Refunds**: Persisted operation keys make interrupted unwinds safe to resume.
*   **Input Validation**: Strict type checking and negative number prevention.
