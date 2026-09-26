# Unicornia External API Documentation

This document describes how to interact with the Unicornia economy system from other Red cogs. The API provides a safe, atomic, and easy-to-use interface for managing user balances.

## Accessing the API

To use the API, you first need to retrieve the loaded `Unicornia` cog instance from the bot.

```python
unicornia = bot.get_cog("Unicornia")
if not unicornia:
    # Handle the case where Unicornia is not loaded
    return
```

## Methods

### `apply_operation(*, key: str, user_id: int, amount: int, direction: OperationDirection, source: str, guild_id: int | None = None, reason: str = "") -> OperationOutcome | None`

Applies a balance effect **exactly once**, keyed by a caller-supplied idempotency key. Other cogs should prefer this
over `add_balance`/`remove_balance` whenever a stable operation identity exists (a reward tied to one event, for
example). Repeating a settled key returns the original result without changing the balance or writing another
transaction-log row, so retries and replayed webhooks never pay twice.

`OperationDirection` and `OperationOutcome` come from `unicornia.db.economy`; `direction` is the literal
`"credit"` to add or `"debit"` to remove, and `amount` is always positive.

**Parameters:**
- `key` (str): Unique idempotency key (e.g. `"nitro:<guild>:<member>:<ts>"`).
- `user_id` (int): The Discord ID of the user whose wallet is mutated.
- `amount` (int): Absolute amount to apply.
- `direction` (OperationDirection): `"credit"` to add, `"debit"` to remove.
- `source` (str): Calling cog/system identity.
- `guild_id` (int, optional): Guild context for the operation.
- `reason` (str, optional): Human-readable reason for the transaction-log row.

**Returns:**
- `OperationOutcome | None`: The outcome of the operation, or `None` if the system was not ready.

**Example:**
```python
outcome = await unicornia.apply_operation(
    key=f"contest:{contest_id}:{ctx.author.id}",
    user_id=ctx.author.id,
    amount=1000,
    direction="credit",
    source="ContestCog",
    reason="Contest prize",
)
```

---

### `get_balance(user_id: int) -> Tuple[int, int]`

Retrieves the current wallet and bank balance for a specific user.

**Parameters:**
- `user_id` (int): The Discord ID of the user.

**Returns:**
- `Tuple[int, int]`: A tuple containing `(wallet_balance, bank_balance)`. Returns `(0, 0)` if the system is not ready.

**Example:**
```python
wallet, bank = await unicornia.get_balance(user_id)
await ctx.send(f"You have {wallet} in wallet and {bank} in bank.")
```

---

### `add_balance(user_id: int, amount: int, reason: str = "External API", source: str = "external") -> bool`

Safely adds currency to a user's wallet. This operation is atomic and logs the transaction.

**Parameters:**
- `user_id` (int): The Discord ID of the user.
- `amount` (int): The amount of currency to add.
- `reason` (str, optional): A human-readable reason for the transaction (e.g., "Event Reward"). Defaults to "External API".
- `source` (str, optional): The name of the source system or cog (e.g., "MyEventCog"). Defaults to "external". This is stored in the `Extra` column of the transaction log.

**Returns:**
- `bool`: `True` if the transaction was successful, `False` if the system was not ready.

**Example:**
```python
success = await unicornia.add_balance(
    user_id=ctx.author.id, amount=1000, reason="Winner of the trivia event", source="TriviaCog"
)
if success:
    await ctx.send("Prize awarded!")
```

---

### `remove_balance(user_id: int, amount: int, reason: str = "External API", source: str = "external") -> bool`

Safely removes currency from a user's wallet. This operation is atomic and checks for sufficient funds before processing.

**Parameters:**
- `user_id` (int): The Discord ID of the user.
- `amount` (int): The amount of currency to remove.
- `reason` (str, optional): A human-readable reason for the transaction (e.g., "Entry Fee"). Defaults to "External API".
- `source` (str, optional): The name of the source system or cog. Defaults to "external". This is stored in the `Extra` column of the transaction log.

**Returns:**
- `bool`: `True` if the transaction was successful. `False` if the user has insufficient funds or the system was not ready.

**Example:**
```python
success = await unicornia.remove_balance(
    user_id=ctx.author.id, amount=500, reason="Purchase of special item", source="ShopCog"
)

if success:
    await ctx.send("Purchase successful!")
else:
    await ctx.send("You do not have enough currency.")
```

## Rank-card backgrounds and read-only views

These are what the Dashboard cog's member and staff pages use. `buy_background` and `use_background` are the only ones
that change anything; the rest never write to the database.

| Method | Returns |
| --- | --- |
| `buy_background(member, key) -> str` | Buys a visible background, charges at most once, equips it, and returns its name. Raises `ValueError` with the reason (not found, not for sale, already owned, not enough currency). |
| `use_background(member, key) -> str` | Equips an owned background, hidden ones included. Raises `ValueError` if it isn't owned. |
| `equipped_backgrounds(user_ids) -> dict[int, str]` | Each user's equipped background key, `"default"` when none, in one query. |
| `background_images(key) -> tuple[str, str]` | `(animated, still)` URLs for the web: `preview` → `url`, and `still` → `preview` → `url`. |
| `backgrounds_for(member) -> list[dict]` | Every buyable background plus hidden ones the member owns, each with `key`, `name`, `price`, `animated`, `still`, `owned` and `equipped`. |
| `xp_ranking(guild) -> list[tuple[int, int]]` | `(user_id, xp)` of current non-bot members, best first, top 300, cached for a minute (shared with `level leaderboard`). |
| `level_stats(xp) -> LevelStats` | Level, XP into the level, XP needed, and total. |
| `member_summary(guild, user_id, *, transactions=20, details=False) -> dict` | Wallet, bank, `LevelStats`, rank (`None` past 300 or without XP), club, equipped background and recent transactions. `details=True` adds rakeback, bet stats, shop inventory and owned backgrounds. |
| `richest(guild, limit=25) -> list[tuple[int, int]]` | `(user_id, wallet + bank)` of current non-bot members. |
| `house_stats() -> dict` | The `[p]unicornia yieldstats` figures as numbers: per-game RTP against the target, the yield pool and recent dividend runs. |
| `config_snapshot(guild) -> dict` | The settings, channels, whitelists and level rewards, without the Nadeko migration path, market message ID or on/off switches. |
| `stocks() -> list[dict]` | Every listed stock. |

## Best Practices

1.  **Check for Cog Existence**: Always check if `bot.get_cog("Unicornia")` returns a value before attempting to call methods.
2.  **Use Meaningful Reasons**: Provide clear `reason` and `source` strings. These are logged in the database and help server administrators audit transactions.
3.  **Handle Return Values**: Always check the boolean return value of `remove_balance` to handle insufficient funds gracefully.
4.  **Async/Await**: All API methods are asynchronous and must be `await`ed.
