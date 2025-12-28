from typing import List, Dict, Any, Tuple

class WaifuRepository:
    """Repository for Waifu system database operations"""
    
    def __init__(self, db):
        self.db = db

    # Waifu System Methods
    async def get_waifu_info(self, waifu_id: int):
        """Get waifu information"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT waifu_id, claimer_id, price, affinity_id, created_at FROM waifus WHERE waifu_id = ?
            """, (waifu_id,))
            return await cursor.fetchone()

    async def claim_waifu(self, waifu_id: int, claimer_id: int, price: int) -> bool:
        """Claim a waifu"""
        async with self.db._get_connection() as db:
            
            # Check if waifu is already claimed
            cursor = await db.execute("SELECT claimer_id FROM waifus WHERE waifu_id = ?", (waifu_id,))
            result = await cursor.fetchone()
            
            if result and result[0] is not None:
                return False  # Already claimed
            
            # Update or insert waifu claim
            await db.execute("""
                INSERT OR REPLACE INTO waifus (waifu_id, claimer_id, price, created_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (waifu_id, claimer_id, price))
            
            # Log waifu update
            await db.execute("""
                INSERT INTO waifu_updates (waifu_id, old_claimer_id, new_claimer_id, update_type, created_at)
                VALUES (?, ?, ?, 'claimed', datetime('now'))
            """, (waifu_id, None, claimer_id))
            
            await db.commit()
            return True

    async def divorce_waifu(self, waifu_id: int, claimer_id: int) -> bool:
        """Divorce a waifu"""
        async with self.db._get_connection() as db:
            
            # Check if user owns this waifu
            cursor = await db.execute("SELECT claimer_id FROM waifus WHERE waifu_id = ?", (waifu_id,))
            result = await cursor.fetchone()
            
            if not result or result[0] != claimer_id:
                return False  # Not owned by this user
            
            # Log divorce
            await db.execute("""
                INSERT INTO waifu_updates (waifu_id, old_claimer_id, new_claimer_id, update_type, created_at)
                VALUES (?, ?, ?, 'divorced', datetime('now'))
            """, (waifu_id, claimer_id, None))
            
            # Remove claim
            await db.execute("""
                UPDATE waifus SET claimer_id = NULL WHERE waifu_id = ?
            """, (waifu_id,))
            
            await db.commit()
            return True

    async def transfer_waifu(self, waifu_id: int, new_owner_id: int, price: int):
        """Transfer waifu ownership"""
        async with self.db._get_connection() as db:
            
            # Get old owner
            cursor = await db.execute("SELECT claimer_id FROM waifus WHERE waifu_id = ?", (waifu_id,))
            result = await cursor.fetchone()
            old_owner_id = result[0] if result else None
            
            # Update waifu
            await db.execute("""
                UPDATE waifus 
                SET claimer_id = ?, price = ? 
                WHERE waifu_id = ?
            """, (new_owner_id, price, waifu_id))
            
            # Log update
            await db.execute("""
                INSERT INTO waifu_updates (waifu_id, old_claimer_id, new_claimer_id, update_type, created_at)
                VALUES (?, ?, ?, 'transfer', datetime('now'))
            """, (waifu_id, old_owner_id, new_owner_id))
            
            await db.commit()

    async def admin_reset_waifu(self, waifu_id: int):
        """Admin reset waifu: remove claimer and set price to 50"""
        async with self.db._get_connection() as db:
            
            # Get old owner for logs
            cursor = await db.execute("SELECT claimer_id FROM waifus WHERE waifu_id = ?", (waifu_id,))
            result = await cursor.fetchone()
            old_owner_id = result[0] if result else None
            
            # Update waifu
            await db.execute("""
                UPDATE waifus 
                SET claimer_id = NULL, price = 50 
                WHERE waifu_id = ?
            """, (waifu_id,))
            
            # Log update
            await db.execute("""
                INSERT INTO waifu_updates (waifu_id, old_claimer_id, new_claimer_id, update_type, created_at)
                VALUES (?, ?, NULL, 'admin_reset', datetime('now'))
            """, (waifu_id, old_owner_id))
            
            await db.commit()
            return True

    async def get_waifu_owner(self, waifu_id: int):
        """Get waifu owner"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT claimer_id FROM waifus WHERE waifu_id = ?", (waifu_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_user_waifus(self, user_id: int):
        """Get all waifus owned by a user"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT waifu_id, price, affinity_id, created_at FROM waifus WHERE claimer_id = ?
                ORDER BY created_at DESC
            """, (user_id,))
            return await cursor.fetchall()

    async def get_waifu_price(self, waifu_id: int) -> int:
        """Get current waifu price"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT price FROM waifus WHERE waifu_id = ?", (waifu_id,))
            result = await cursor.fetchone()
            return result[0] if result else 50  # Default price

    async def update_waifu_price(self, waifu_id: int, new_price: int):
        """Update waifu price"""
        async with self.db._get_connection() as db:
            await db.execute("""
                UPDATE waifus SET price = ? WHERE waifu_id = ?
            """, (new_price, waifu_id))
            await db.commit()

    async def set_waifu_affinity(self, waifu_id: int, affinity_id: int):
        """Set waifu affinity"""
        async with self.db._get_connection() as db:
            await db.execute("""
                UPDATE waifus SET affinity_id = ? WHERE waifu_id = ?
            """, (affinity_id, waifu_id))
            await db.commit()

    async def get_waifu_affinity(self, waifu_id: int):
        """Get waifu affinity"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT affinity_id FROM waifus WHERE waifu_id = ?", (waifu_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_waifu_leaderboard(self, limit: int = 10):
        """Get waifu leaderboard by price"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT waifu_id, claimer_id, price FROM waifus 
                WHERE claimer_id IS NOT NULL 
                ORDER BY price DESC LIMIT ?
            """, (limit,))
            return await cursor.fetchall()

    async def add_waifu_item(self, waifu_id: int, name: str, emoji: str):
        """Add item to waifu"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT INTO waifu_items (waifu_id, name, emoji, created_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (waifu_id, name, emoji))
            await db.commit()

    async def get_waifu_items(self, waifu_id: int):
        """Get waifu items"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT name, emoji FROM waifu_items WHERE waifu_id = ?
                ORDER BY created_at DESC
            """, (waifu_id,))
            return await cursor.fetchall()

    async def get_waifu_history(self, waifu_id: int, limit: int = 10):
        """Get waifu transaction history"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT old_claimer_id, new_claimer_id, update_type, created_at 
                FROM waifu_updates WHERE waifu_id = ? 
                ORDER BY created_at DESC LIMIT ?
            """, (waifu_id, limit))
            return await cursor.fetchall()
