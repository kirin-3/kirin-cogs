"""
Stock Market Database Logic
"""

import logging
import re

import aiosqlite

from ..stock_market import INITIAL_SHARE_RESERVE, P_BASE
from .core import CoreDB

log = logging.getLogger("red.kirin_cogs.unicornia.database")


class StockRepository:
    """Handles database operations for the Stock Market"""

    def __init__(self, db: CoreDB):
        self.db = db

    async def _insert_transaction(
        self,
        db: aiosqlite.Connection,
        *,
        user_id: int,
        symbol: str,
        side: str,
        shares: int,
        exec_price: float,
        tax: int,
        total_amount: int,
        kind: str = "trade",
        is_imported: bool = False,
        date_added: str | None = None,
    ) -> None:
        """Insert one stock-ledger row using an existing transaction."""
        await db.execute(
            """
            INSERT INTO StockTransactions
                (UserId, Symbol, Side, Kind, Shares, ExecPrice, Tax, TotalAmount, IsImported, DateAdded)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))
            """,
            (
                user_id,
                symbol.upper(),
                side,
                kind,
                shares,
                exec_price,
                tax,
                total_amount,
                int(is_imported),
                date_added,
            ),
        )

    async def add_transaction(
        self,
        *,
        user_id: int,
        symbol: str,
        side: str,
        shares: int,
        exec_price: float,
        tax: int,
        total_amount: int,
        kind: str = "trade",
        is_imported: bool = False,
        date_added: str | None = None,
    ) -> None:
        """Write one standalone stock-ledger row."""
        async with self.db._get_connection() as db:
            await self._insert_transaction(
                db,
                user_id=user_id,
                symbol=symbol,
                side=side,
                shares=shares,
                exec_price=exec_price,
                tax=tax,
                total_amount=total_amount,
                kind=kind,
                is_imported=is_imported,
                date_added=date_added,
            )
            await db.commit()

    async def execute_buy(
        self,
        *,
        user_id: int,
        symbol: str,
        shares: int,
        exec_price: float,
        tax: int,
        total_cost: int,
        spot_after: float,
        reserve_after: float,
    ) -> bool:
        """Apply a buy and its exact ledger row in one transaction."""
        symbol = symbol.upper()
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                debit = await db.execute(
                    """
                    UPDATE DiscordUser SET CurrencyAmount = CurrencyAmount - ?
                    WHERE UserId = ? AND CurrencyAmount >= ?
                    """,
                    (total_cost, user_id, total_cost),
                )
                if debit.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return False

                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions
                        (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, 'stock_buy', 'market', NULL, ?, datetime('now'))
                    """,
                    (user_id, -total_cost, f"Bought {shares} {symbol} (Tax: {tax})"),
                )
                row = await (
                    await db.execute(
                        "SELECT Amount, AverageCost FROM StockHoldings WHERE UserId = ? AND Symbol = ?",
                        (user_id, symbol),
                    )
                ).fetchone()
                current_shares = int(row[0]) if row else 0
                current_cost = float(row[1]) if row else 0.0
                new_shares = current_shares + shares
                average_cost = ((current_shares * current_cost) + total_cost) / new_shares
                await db.execute(
                    """
                    INSERT INTO StockHoldings (UserId, Symbol, Amount, AverageCost)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(UserId, Symbol) DO UPDATE SET
                        Amount = excluded.Amount, AverageCost = excluded.AverageCost
                    """,
                    (user_id, symbol, new_shares, average_cost),
                )
                await db.execute(
                    """
                    UPDATE Stocks
                    SET TotalShares = TotalShares + ?,
                        CurrentPrice = ?,
                        ShareReserve = ?
                    WHERE Symbol = ?
                    """,
                    (shares, spot_after, reserve_after, symbol),
                )
                await self._insert_transaction(
                    db,
                    user_id=user_id,
                    symbol=symbol,
                    side="buy",
                    shares=shares,
                    exec_price=exec_price,
                    tax=tax,
                    total_amount=-total_cost,
                )
                await db.commit()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def execute_sell(
        self,
        *,
        user_id: int,
        symbol: str,
        shares: int,
        exec_price: float,
        tax: int,
        total_payout: int,
        spot_after: float,
        reserve_after: float,
    ) -> bool:
        """Apply a sell and its exact ledger row in one transaction."""
        symbol = symbol.upper()
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                row = await (
                    await db.execute(
                        "SELECT Amount FROM StockHoldings WHERE UserId = ? AND Symbol = ?",
                        (user_id, symbol),
                    )
                ).fetchone()
                if row is None or int(row[0]) < shares:
                    await db.execute("ROLLBACK")
                    return False

                remaining = int(row[0]) - shares
                if remaining:
                    await db.execute(
                        "UPDATE StockHoldings SET Amount = ? WHERE UserId = ? AND Symbol = ?",
                        (remaining, user_id, symbol),
                    )
                else:
                    await db.execute(
                        "DELETE FROM StockHoldings WHERE UserId = ? AND Symbol = ?",
                        (user_id, symbol),
                    )
                await db.execute(
                    """
                    INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                    ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + excluded.CurrencyAmount
                    """,
                    (user_id, total_payout),
                )
                await db.execute(
                    """
                    INSERT INTO CurrencyTransactions
                        (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, 'stock_sell', 'market', NULL, ?, datetime('now'))
                    """,
                    (user_id, total_payout, f"Sold {shares} {symbol} (Tax: {tax})"),
                )
                await db.execute(
                    """
                    UPDATE Stocks
                    SET TotalShares = TotalShares - ?,
                        CurrentPrice = ?,
                        ShareReserve = ?
                    WHERE Symbol = ?
                    """,
                    (shares, spot_after, reserve_after, symbol),
                )
                await self._insert_transaction(
                    db,
                    user_id=user_id,
                    symbol=symbol,
                    side="sell",
                    shares=shares,
                    exec_price=exec_price,
                    tax=tax,
                    total_amount=total_payout,
                )
                await db.commit()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def get_transactions(self, user_id: int) -> list[dict]:
        """Return the user's complete structured stock-trade history."""
        async with self.db._get_connection() as db:
            rows = await (
                await db.execute(
                    """
                    SELECT Symbol, Side, Kind, Shares, ExecPrice, Tax, TotalAmount, IsImported, DateAdded
                    FROM StockTransactions WHERE UserId = ?
                    ORDER BY DateAdded DESC, Id DESC
                    """,
                    (user_id,),
                )
            ).fetchall()
        return [
            {
                "symbol": row[0],
                "action": "Unwound" if row[2] == "unwind" else ("Bought" if row[1] == "buy" else "Sold"),
                "kind": row[2],
                "shares": row[3],
                "price": row[4],
                "tax": row[5],
                "total": abs(row[6]),
                "imported": bool(row[7]),
                "date": row[8],
            }
            for row in rows
        ]

    async def backfill_legacy_transactions(self) -> tuple[int, int]:
        """Import parseable legacy stock transaction reasons exactly once."""
        trade_pattern = re.compile(r"^(Bought|Sold)\s+(\d+)\s+([^\s@]+)", re.IGNORECASE)
        price_pattern = re.compile(r"@\s*~?([\d.]+)")
        tax_pattern = re.compile(r"Tax:\s*(\d+)", re.IGNORECASE)

        async with self.db._get_connection() as db:
            row = await (await db.execute("SELECT Value FROM BotConfig WHERE Key = 'StockLedgerBackfilled'")).fetchone()
            if row and str(row[0]).strip().lower() in {"1", "true", "yes"}:
                return (0, 0)

            await db.execute("BEGIN")
            try:
                rows = await (
                    await db.execute(
                        """
                        SELECT UserId, Type, Amount, Reason, DateAdded
                        FROM CurrencyTransactions
                        WHERE Type IN ('stock_buy', 'stock_sell')
                        ORDER BY Id
                        """
                    )
                ).fetchall()
                imported = 0
                skipped = 0
                for user_id, transaction_type, amount, reason, date_added in rows:
                    match = trade_pattern.search(reason or "")
                    if match is None:
                        skipped += 1
                        continue
                    action, shares, symbol = match.groups()
                    price_match = price_pattern.search(reason or "")
                    tax_match = tax_pattern.search(reason or "")
                    await self._insert_transaction(
                        db,
                        user_id=int(user_id),
                        symbol=symbol,
                        side="buy" if action.lower() == "bought" or transaction_type == "stock_buy" else "sell",
                        shares=int(shares),
                        exec_price=float(price_match.group(1)) if price_match else 0.0,
                        tax=int(tax_match.group(1)) if tax_match else 0,
                        total_amount=int(amount),
                        is_imported=True,
                        date_added=str(date_added),
                    )
                    imported += 1

                await db.execute(
                    """
                    INSERT INTO BotConfig (Key, Value, Description)
                    VALUES ('StockLedgerBackfilled', '1', 'Whether legacy stock transactions were imported')
                    ON CONFLICT(Key) DO UPDATE SET Value = excluded.Value
                    """
                )
                await db.commit()
            except Exception:
                await db.execute("ROLLBACK")
                raise

        log.info("Stock ledger backfill completed: %s imported, %s skipped", imported, skipped)
        return imported, skipped

    async def create_stock(self, symbol: str, name: str, emoji: str, price: int) -> bool:
        """Create a new stock (IPO)."""
        async with self.db._get_connection() as db:
            try:
                await db.execute(
                    """
                    INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice, PreviousPrice, TotalShares, Volatility, Hidden)
                    VALUES (?, ?, ?, ?, ?, 0, 1.0, 0)
                """,
                    (symbol.upper(), name, emoji, price, price),
                )
                await db.commit()
                return True
            except Exception as e:
                log.error(f"Failed to create stock {symbol}: {e}")
                return False

    async def get_stock(self, symbol: str) -> dict | None:
        """Get stock details by symbol."""
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT Symbol, Name, Emoji, CurrentPrice, PreviousPrice, TotalShares,
                       ShareReserve, SmoothedUsage, Volatility, Hidden
                FROM Stocks WHERE Symbol = ?
            """,
                (symbol.upper(),),
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "symbol": row[0],
                    "name": row[1],
                    "emoji": row[2],
                    "price": row[3],
                    "previous_price": row[4],
                    "total_shares": row[5],
                    "share_reserve": row[6],
                    "smoothed_usage": row[7],
                    "volatility": row[8],
                    "hidden": bool(row[9]),
                }
            return None

    async def get_all_stocks(self, include_hidden: bool = False) -> list[dict]:
        """Get all stocks."""
        query = """
            SELECT Symbol, Name, Emoji, CurrentPrice, PreviousPrice, TotalShares,
                   ShareReserve, SmoothedUsage, Volatility, Hidden
            FROM Stocks
        """
        if not include_hidden:
            query += " WHERE Hidden = 0"

        async with self.db._get_connection() as db:
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            return [
                {
                    "symbol": row[0],
                    "name": row[1],
                    "emoji": row[2],
                    "price": row[3],
                    "previous_price": row[4],
                    "total_shares": row[5],
                    "share_reserve": row[6],
                    "smoothed_usage": row[7],
                    "volatility": row[8],
                    "hidden": bool(row[9]),
                }
                for row in rows
            ]

    async def update_stock_price(self, symbol: str, new_price: float, update_previous: bool = False) -> bool:
        """Update stock price."""
        query = "UPDATE Stocks SET CurrentPrice = ?"
        params: list = [new_price]

        if update_previous:
            # If updating previous, we set previous = current (before this update)
            # This is tricky in one query if we want previous to be the OLD current.
            # Usually 'update_previous' means we are ticking the market.
            # Let's assume the caller handles the logic or we do it here.
            # For simplicity: usage pattern is usually bulk update.
            pass

        query += " WHERE Symbol = ?"
        params.append(symbol.upper())

        async with self.db._get_connection() as db:
            await db.execute(query, tuple(params))
            await db.commit()
            return True

    async def bulk_update_prices(
        self,
        updates: list[tuple[str, float, float, float]],
        *,
        completed_at: int | None = None,
    ) -> None:
        """Update multiple stock prices at once (Market Tick).
        updates: List of (Symbol, NewPrice, PreviousPrice, SmoothedUsage)

        When supplied, ``completed_at`` is persisted in the same transaction
        so a committed economic tick can never be replayed after a later UI
        failure.
        """
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                await db.executemany(
                    """
                    UPDATE Stocks
                    SET CurrentPrice = ?, PreviousPrice = ?, SmoothedUsage = ?
                    WHERE Symbol = ?
                    """,
                    [(p, pp, usage, s) for s, p, pp, usage in updates],
                )
                if completed_at is not None:
                    await db.execute(
                        """
                        INSERT INTO BotConfig (Key, Value, Description)
                        VALUES ('LastMarketTick', ?, 'Timestamp of last completed market tick')
                        ON CONFLICT(Key) DO UPDATE SET Value = excluded.Value
                        """,
                        (str(completed_at),),
                    )
                await db.commit()
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def update_shares_and_price(self, symbol: str, shares_delta: int, price_delta: float) -> bool:
        """Atomic update for transactions (buy/sell)."""
        async with self.db._get_connection() as db:
            # Update TotalShares and CurrentPrice
            await db.execute(
                """
                UPDATE Stocks
                SET TotalShares = TotalShares + ?,
                    CurrentPrice = MAX(1, CurrentPrice + ?)
                WHERE Symbol = ?
            """,
                (shares_delta, price_delta, symbol.upper()),
            )
            await db.commit()
            return True

    async def get_unwind_records(self) -> tuple[list[dict], list[dict]]:
        """Load the immutable source rows used to plan a stock unwind."""
        async with self.db._get_connection() as db:
            holding_rows = await (
                await db.execute(
                    """
                    SELECT UserId, Symbol, Amount, AverageCost
                    FROM StockHoldings
                    WHERE Amount > 0
                    ORDER BY UserId, Symbol
                    """
                )
            ).fetchall()
            ledger_rows = await (
                await db.execute(
                    """
                    SELECT UserId, Symbol, Side, Kind, Shares, ExecPrice, Tax, TotalAmount, IsImported
                    FROM StockTransactions
                    ORDER BY DateAdded, Id
                    """
                )
            ).fetchall()
        holdings = [
            {"user_id": row[0], "symbol": row[1], "amount": row[2], "average_cost": row[3]} for row in holding_rows
        ]
        ledger = [
            {
                "user_id": row[0],
                "symbol": row[1],
                "side": row[2],
                "kind": row[3],
                "shares": row[4],
                "exec_price": row[5],
                "tax": row[6],
                "total_amount": row[7],
                "imported": bool(row[8]),
            }
            for row in ledger_rows
        ]
        return holdings, ledger

    async def close_unwound_holding(
        self,
        *,
        user_id: int,
        symbol: str,
        shares: int,
        per_share_cost: float,
        refund: int,
    ) -> bool:
        """Delete one paid holding and write its unwind ledger row atomically."""
        symbol = symbol.upper()
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                deleted = await db.execute(
                    "DELETE FROM StockHoldings WHERE UserId = ? AND Symbol = ? AND Amount = ?",
                    (user_id, symbol, shares),
                )
                if deleted.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return False
                await self._insert_transaction(
                    db,
                    user_id=user_id,
                    symbol=symbol,
                    side="sell",
                    kind="unwind",
                    shares=shares,
                    exec_price=per_share_cost,
                    tax=0,
                    total_amount=refund,
                )
                await db.commit()
                return True
            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def reset_market(self) -> None:
        """Return all stocks to the configured flat opening state."""
        async with self.db._get_connection() as db:
            await db.execute(
                """
                UPDATE Stocks
                SET TotalShares = 0, ShareReserve = ?, CurrentPrice = ?, PreviousPrice = ?
                """,
                (INITIAL_SHARE_RESERVE, P_BASE, P_BASE),
            )
            await db.commit()

    async def get_unwind_run_id(self) -> str | None:
        """Return the persisted resumable unwind identifier, if any."""
        async with self.db._get_connection() as db:
            row = await (await db.execute("SELECT Value FROM BotConfig WHERE Key = 'StockUnwindRunId'")).fetchone()
        return str(row[0]) if row and row[0] else None

    async def set_unwind_run_id(self, run_id: str) -> None:
        """Persist an unwind identifier before applying its first refund."""
        async with self.db._get_connection() as db:
            await db.execute(
                """
                INSERT INTO BotConfig (Key, Value, Description)
                VALUES ('StockUnwindRunId', ?, 'Resumable stock unwind run identifier')
                ON CONFLICT(Key) DO UPDATE SET Value = excluded.Value
                """,
                (run_id,),
            )
            await db.commit()

    async def clear_unwind_run_id(self) -> None:
        """Clear the resumable identifier after a successful unwind."""
        async with self.db._get_connection() as db:
            await db.execute("DELETE FROM BotConfig WHERE Key = 'StockUnwindRunId'")
            await db.commit()

    async def delete_stock(self, symbol: str) -> bool:
        """Delete a stock."""
        async with self.db._get_connection() as db:
            await db.execute("DELETE FROM Stocks WHERE Symbol = ?", (symbol.upper(),))
            await db.commit()
            return True

    # Holdings

    async def get_user_holdings(self, user_id: int) -> list[dict]:
        """Get all holdings for a user."""
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT h.Symbol, h.Amount, h.AverageCost, s.CurrentPrice, s.Name, s.Emoji
                FROM StockHoldings h
                JOIN Stocks s ON h.Symbol = s.Symbol
                WHERE h.UserId = ? AND h.Amount > 0
            """,
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "symbol": row[0],
                    "amount": row[1],
                    "average_cost": row[2],
                    "current_price": row[3],
                    "name": row[4],
                    "emoji": row[5],
                }
                for row in rows
            ]

    async def get_holding(self, user_id: int, symbol: str) -> dict | None:
        """Get specific holding."""
        async with self.db._get_connection() as db:
            cursor = await db.execute(
                """
                SELECT Amount, AverageCost FROM StockHoldings
                WHERE UserId = ? AND Symbol = ?
            """,
                (user_id, symbol.upper()),
            )
            row = await cursor.fetchone()
            if row:
                return {"amount": row[0], "average_cost": row[1]}
            return None

    async def get_held_shares_counts(self) -> dict[str, int]:
        """Get total shares held by users for all stocks."""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Symbol, SUM(Amount)
                FROM StockHoldings
                GROUP BY Symbol
            """)
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

    async def update_holding(
        self, user_id: int, symbol: str, amount_delta: int, cost_basis_update: float | None = None
    ) -> bool:
        """Update user holding (Buy/Sell).
        amount_delta: + for buy, - for sell.
        cost_basis_update: New average cost (calculated by caller logic).
        """
        symbol = symbol.upper()
        async with self.db._get_connection() as db:
            # Check existing
            cursor = await db.execute(
                "SELECT Amount, AverageCost FROM StockHoldings WHERE UserId = ? AND Symbol = ?", (user_id, symbol)
            )
            row = await cursor.fetchone()

            current_amount = row[0] if row else 0
            # current_cost = row[1] if row else 0

            new_amount = current_amount + amount_delta

            if new_amount < 0:
                return False  # Cannot have negative shares

            if new_amount == 0:
                await db.execute("DELETE FROM StockHoldings WHERE UserId = ? AND Symbol = ?", (user_id, symbol))
            else:
                if cost_basis_update is not None:
                    # Upsert
                    await db.execute(
                        """
                        INSERT OR REPLACE INTO StockHoldings (UserId, Symbol, Amount, AverageCost)
                        VALUES (?, ?, ?, ?)
                    """,
                        (user_id, symbol, new_amount, cost_basis_update),
                    )
                else:
                    # Only update amount (e.g. for gifts/drops if we don't change cost basis? typically we should)
                    # If selling, cost basis doesn't change per share, but total value does.
                    # Usually we update AverageCost only on Buy. On Sell we keep AverageCost same.
                    # So cost_basis_update should be passed appropriately.
                    await db.execute(
                        """
                        UPDATE StockHoldings SET Amount = ? WHERE UserId = ? AND Symbol = ?
                    """,
                        (new_amount, user_id, symbol),
                    )

            await db.commit()
            return True
