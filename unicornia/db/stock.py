"""
Stock Market Database Logic
"""

import logging
from typing import List, Tuple, Optional, Dict
from .core import CoreDB

log = logging.getLogger("red.kirin_cogs.unicornia.database")

class StockRepository:
    """Handles database operations for the Stock Market"""
    
    def __init__(self, db: CoreDB):
        self.db = db

    async def create_stock(self, symbol: str, name: str, emoji: str, price: int) -> bool:
        """Create a new stock (IPO)."""
        async with self.db._get_connection() as db:
            try:
                await db.execute("""
                    INSERT INTO Stocks (Symbol, Name, Emoji, CurrentPrice, PreviousPrice, TotalShares, Volatility, Hidden)
                    VALUES (?, ?, ?, ?, ?, 0, 1.0, 0)
                """, (symbol.upper(), name, emoji, price, price))
                await db.commit()
                return True
            except Exception as e:
                log.error(f"Failed to create stock {symbol}: {e}")
                return False

    async def get_stock(self, symbol: str) -> Optional[dict]:
        """Get stock details by symbol."""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Symbol, Name, Emoji, CurrentPrice, PreviousPrice, TotalShares, Volatility, Hidden
                FROM Stocks WHERE Symbol = ?
            """, (symbol.upper(),))
            row = await cursor.fetchone()
            if row:
                return {
                    "symbol": row[0],
                    "name": row[1],
                    "emoji": row[2],
                    "price": row[3],
                    "previous_price": row[4],
                    "total_shares": row[5],
                    "volatility": row[6],
                    "hidden": bool(row[7])
                }
            return None

    async def get_all_stocks(self, include_hidden: bool = False) -> List[dict]:
        """Get all stocks."""
        query = "SELECT Symbol, Name, Emoji, CurrentPrice, PreviousPrice, TotalShares, Volatility, Hidden FROM Stocks"
        if not include_hidden:
            query += " WHERE Hidden = 0"
        
        async with self.db._get_connection() as db:
            cursor = await db.execute(query)
            rows = await cursor.fetchall()
            return [{
                "symbol": row[0],
                "name": row[1],
                "emoji": row[2],
                "price": row[3],
                "previous_price": row[4],
                "total_shares": row[5],
                "volatility": row[6],
                "hidden": bool(row[7])
            } for row in rows]

    async def update_stock_price(self, symbol: str, new_price: int, update_previous: bool = False) -> bool:
        """Update stock price."""
        query = "UPDATE Stocks SET CurrentPrice = ?"
        params = [new_price]
        
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

    async def bulk_update_prices(self, updates: List[Tuple[str, int, int]]) -> None:
        """Update multiple stock prices at once (Market Tick).
        updates: List of (Symbol, NewPrice, PreviousPrice)
        """
        async with self.db._get_connection() as db:
            await db.executemany("""
                UPDATE Stocks 
                SET CurrentPrice = ?, PreviousPrice = ?
                WHERE Symbol = ?
            """, [(p, pp, s) for s, p, pp in updates])
            await db.commit()

    async def update_shares_and_price(self, symbol: str, shares_delta: int, price_delta: float) -> bool:
        """Atomic update for transactions (buy/sell)."""
        async with self.db._get_connection() as db:
            # Update TotalShares and CurrentPrice
            await db.execute("""
                UPDATE Stocks
                SET TotalShares = TotalShares + ?,
                    CurrentPrice = MAX(1, CAST(CurrentPrice + ? AS INTEGER))
                WHERE Symbol = ?
            """, (shares_delta, price_delta, symbol.upper()))
            await db.commit()
            return True

    async def delete_stock(self, symbol: str) -> bool:
        """Delete a stock."""
        async with self.db._get_connection() as db:
            await db.execute("DELETE FROM Stocks WHERE Symbol = ?", (symbol.upper(),))
            await db.commit()
            return True

    # Holdings

    async def get_user_holdings(self, user_id: int) -> List[dict]:
        """Get all holdings for a user."""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT h.Symbol, h.Amount, h.AverageCost, s.CurrentPrice, s.Name, s.Emoji
                FROM StockHoldings h
                JOIN Stocks s ON h.Symbol = s.Symbol
                WHERE h.UserId = ? AND h.Amount > 0
            """, (user_id,))
            rows = await cursor.fetchall()
            return [{
                "symbol": row[0],
                "amount": row[1],
                "average_cost": row[2],
                "current_price": row[3],
                "name": row[4],
                "emoji": row[5]
            } for row in rows]

    async def get_holding(self, user_id: int, symbol: str) -> Optional[dict]:
        """Get specific holding."""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Amount, AverageCost FROM StockHoldings
                WHERE UserId = ? AND Symbol = ?
            """, (user_id, symbol.upper()))
            row = await cursor.fetchone()
            if row:
                return {"amount": row[0], "average_cost": row[1]}
            return None

    async def update_holding(self, user_id: int, symbol: str, amount_delta: int, cost_basis_update: float = None) -> bool:
        """Update user holding (Buy/Sell).
        amount_delta: + for buy, - for sell.
        cost_basis_update: New average cost (calculated by caller logic).
        """
        symbol = symbol.upper()
        async with self.db._get_connection() as db:
            # Check existing
            cursor = await db.execute("SELECT Amount, AverageCost FROM StockHoldings WHERE UserId = ? AND Symbol = ?", (user_id, symbol))
            row = await cursor.fetchone()
            
            current_amount = row[0] if row else 0
            # current_cost = row[1] if row else 0
            
            new_amount = current_amount + amount_delta
            
            if new_amount < 0:
                return False # Cannot have negative shares
            
            if new_amount == 0:
                await db.execute("DELETE FROM StockHoldings WHERE UserId = ? AND Symbol = ?", (user_id, symbol))
            else:
                if cost_basis_update is not None:
                    # Upsert
                    await db.execute("""
                        INSERT OR REPLACE INTO StockHoldings (UserId, Symbol, Amount, AverageCost)
                        VALUES (?, ?, ?, ?)
                    """, (user_id, symbol, new_amount, cost_basis_update))
                else:
                    # Only update amount (e.g. for gifts/drops if we don't change cost basis? typically we should)
                    # If selling, cost basis doesn't change per share, but total value does. 
                    # Usually we update AverageCost only on Buy. On Sell we keep AverageCost same.
                    # So cost_basis_update should be passed appropriately.
                    await db.execute("""
                        UPDATE StockHoldings SET Amount = ? WHERE UserId = ? AND Symbol = ?
                    """, (new_amount, user_id, symbol))
            
            await db.commit()
            return True
