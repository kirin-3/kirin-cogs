# Nitro Shop Design Plan

## 1. Overview
A specialized shop system for purchasing Nitro Boost and Nitro Basic subscriptions using "Slut points" (Unicornia currency). This system is separate from the main `ShopSystem` to handle the specific requirements for stock management and manual delivery notifications.

## 2. Data Storage
We will use `redbot.core.Config` for lightweight, persistent storage of stock values.

**Config Scope:** `Global` (Simpler for single-instance bot) or `Guild` (If multi-guild support is needed). Given the hardcoded channel ID, we will default to `Global` for stock to match the "single community" nature, but `Guild` is safer for future-proofing.
*Decision:* **Global** (matches the hardcoded channel requirement better).

**Schema:**
```python
{
    "stocks": {
        "boost": 0, # Integer count
        "basic": 0  # Integer count
    },
    "prices": {
        "boost": 250000,
        "basic": 150000
    }
}
```

## 3. Class Structure

### `NitroSystem`
**Location:** `unicornia/systems/nitro_system.py`

**Responsibilities:**
- Manage stock levels.
- Handle purchase transactions.
- Send notifications.

**Methods:**
- `__init__(bot, config, economy_system)`
- `async def get_stock(self, item_type: str) -> int`
- `async def add_stock(self, item_type: str, amount: int) -> int`:
    - Updates config.
    - Triggers `_announce_stock(item_type, amount)`.
- `async def set_price(self, item_type: str, price: int) -> int`:
    - Updates config.
- `async def purchase_nitro(self, ctx, item_type: str) -> tuple[bool, str]`:
    - Checks stock > 0.
    - Checks user balance (`economy_system.get_balance`).
    - Deducts currency (`economy_system.withdraw`).
    - Decrements stock.
    - Triggers `_notify_admin(ctx, item_type)`.
- `async def _announce_stock(self, item_type: str, amount: int)`:
    - Sends embed to channel `695155004507422730`.
- `async def _notify_admin(self, ctx, item_type: str)`:
    - DMs the Bot Owner(s) with purchase details for manual delivery.
    - DMs user ID `140186220255903746` with purchase details.

## 4. UI Design

### `NitroShopView`
**Location:** `unicornia/views.py`

**Layout:**
- **Embed**:
    - Title: "Nitro Shop"
    - Description: "Exchange your hard-earned points for Discord Nitro!"
    - Fields:
        - **Nitro Boost**: Price: 250k | Stock: {x}
        - **Nitro Basic**: Price: 150k | Stock: {y}
- **Buttons**:
    - `[Buy Nitro Boost]` (Style: Primary/Blurple)
        - Disabled if stock == 0 or user balance < 250k.
    - `[Buy Nitro Basic]` (Style: Secondary/Grey)
        - Disabled if stock == 0 or user balance < 150k.

**Interaction Flow:**
1. User clicks Buy button.
2. Bot sends ephemeral confirmation ("Are you sure you want to buy X for Y?").
3. User confirms.
4. Transaction processes.
5. Bot replies ephemeral success ("Purchase successful! An admin has been notified to send your code.").

## 5. Command Structure

### `NitroCommands`
**Location:** `unicornia/commands/nitro.py`

**Commands:**
- `[p]nitroshop`
    - **Permission**: Public
    - **Action**: Displays `NitroShopView`.
- `[p]nitrostock <type> <amount>`
    - **Permission**: Bot Owner Only (`@commands.is_owner()`)
    - **Arguments**:
        - `type`: "boost" or "basic"
        - `amount`: Integer (can be negative to remove stock)
    - **Action**: Calls `NitroSystem.add_stock`.
- `[p]nitroprice <type> <price>`
    - **Permission**: Bot Owner Only (`@commands.is_owner()`)
    - **Arguments**:
        - `type`: "boost" or "basic"
        - `price`: Integer
    - **Action**: Calls `NitroSystem.set_price`.

## 6. Integration
- Update `Unicornia` class in `unicornia.py`:
    - Initialize `NitroSystem` in `cog_load`.
    - Inherit `NitroCommands`.