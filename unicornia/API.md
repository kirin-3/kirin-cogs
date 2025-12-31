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
- `source` (str, optional): The name of the source system or cog (e.g., "MyEventCog"). Defaults to "external".

**Returns:**
- `bool`: `True` if the transaction was successful, `False` if the system was not ready.

**Example:**
```python
success = await unicornia.add_balance(
    user_id=ctx.author.id,
    amount=1000,
    reason="Winner of the trivia event",
    source="TriviaCog"
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
- `source` (str, optional): The name of the source system or cog. Defaults to "external".

**Returns:**
- `bool`: `True` if the transaction was successful. `False` if the user has insufficient funds or the system was not ready.

**Example:**
```python
success = await unicornia.remove_balance(
    user_id=ctx.author.id,
    amount=500,
    reason="Purchase of special item",
    source="ShopCog"
)

if success:
    await ctx.send("Purchase successful!")
else:
    await ctx.send("You do not have enough currency.")
```

## Best Practices

1.  **Check for Cog Existence**: Always check if `bot.get_cog("Unicornia")` returns a value before attempting to call methods.
2.  **Use Meaningful Reasons**: Provide clear `reason` and `source` strings. These are logged in the database and help server administrators audit transactions.
3.  **Handle Return Values**: Always check the boolean return value of `remove_balance` to handle insufficient funds gracefully.
4.  **Async/Await**: All API methods are asynchronous and must be `await`ed.
