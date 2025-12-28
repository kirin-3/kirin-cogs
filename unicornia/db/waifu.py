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
                SELECT WaifuId, ClaimerId, Price, Affinity, DateAdded FROM WaifuInfo WHERE WaifuId = ?
            """, (waifu_id,))
            return await cursor.fetchone()

    async def claim_waifu(self, waifu_id: int, claimer_id: int, price: int) -> bool:
        """Claim a waifu"""
        async with self.db._get_connection() as db:
            
            # Check if waifu is already claimed
            cursor = await db.execute("SELECT ClaimerId FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            
            if result and result[0] is not None:
                return False  # Already claimed
            
            # Update or insert waifu claim
            await db.execute("""
                INSERT OR REPLACE INTO WaifuInfo (WaifuId, ClaimerId, Price, DateAdded)
                VALUES (?, ?, ?, datetime('now'))
            """, (waifu_id, claimer_id, price))
            
            # Log waifu update (Claimed = 0)
            await db.execute("""
                INSERT INTO WaifuUpdate (UserId, OldId, NewId, UpdateType, DateAdded)
                VALUES (?, ?, ?, 0, datetime('now'))
            """, (waifu_id, 0, claimer_id))
            
            await db.commit()
            return True

    async def divorce_waifu(self, waifu_id: int, claimer_id: int) -> bool:
        """Divorce a waifu"""
        async with self.db._get_connection() as db:
            
            # Check if user owns this waifu
            cursor = await db.execute("SELECT ClaimerId FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            
            if not result or result[0] != claimer_id:
                return False  # Not owned by this user
            
            # Log divorce (Divorced = 1) - Note: Nadeko likely uses UserId as the Waifu ID here
            await db.execute("""
                INSERT INTO WaifuUpdate (UserId, OldId, NewId, UpdateType, DateAdded)
                VALUES (?, ?, ?, 1, datetime('now'))
            """, (waifu_id, claimer_id, 0))
            
            # Remove claim
            await db.execute("""
                UPDATE WaifuInfo SET ClaimerId = NULL WHERE WaifuId = ?
            """, (waifu_id,))
            
            await db.commit()
            return True

    async def transfer_waifu(self, waifu_id: int, new_owner_id: int, price: int):
        """Transfer waifu ownership"""
        async with self.db._get_connection() as db:
            
            # Get old owner
            cursor = await db.execute("SELECT ClaimerId FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            old_owner_id = result[0] if result else 0
            
            # Update waifu
            await db.execute("""
                UPDATE WaifuInfo
                SET ClaimerId = ?, Price = ?
                WHERE WaifuId = ?
            """, (new_owner_id, price, waifu_id))
            
            # Log update (Transfer = 2? Assuming UpdateType enum)
            await db.execute("""
                INSERT INTO WaifuUpdate (UserId, OldId, NewId, UpdateType, DateAdded)
                VALUES (?, ?, ?, 2, datetime('now'))
            """, (waifu_id, old_owner_id, new_owner_id))
            
            await db.commit()

    async def admin_reset_waifu(self, waifu_id: int):
        """Admin reset waifu: remove claimer and set price to 50"""
        async with self.db._get_connection() as db:
            
            # Get old owner for logs
            cursor = await db.execute("SELECT ClaimerId FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            old_owner_id = result[0] if result else 0
            
            # Update waifu
            await db.execute("""
                UPDATE WaifuInfo
                SET ClaimerId = NULL, Price = 50
                WHERE WaifuId = ?
            """, (waifu_id,))
            
            # Log update
            await db.execute("""
                INSERT INTO WaifuUpdate (UserId, OldId, NewId, UpdateType, DateAdded)
                VALUES (?, ?, 0, 99, datetime('now'))
            """, (waifu_id, old_owner_id))
            
            await db.commit()
            return True

    async def get_waifu_owner(self, waifu_id: int):
        """Get waifu owner"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT ClaimerId FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_user_waifus(self, user_id: int):
        """Get all waifus owned by a user"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT WaifuId, Price, Affinity, DateAdded FROM WaifuInfo WHERE ClaimerId = ?
                ORDER BY DateAdded DESC
            """, (user_id,))
            return await cursor.fetchall()

    async def get_waifu_price(self, waifu_id: int) -> int:
        """Get current waifu price"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT Price FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            return result[0] if result else 50  # Default price

    async def update_waifu_price(self, waifu_id: int, new_price: int):
        """Update waifu price"""
        async with self.db._get_connection() as db:
            await db.execute("""
                UPDATE WaifuInfo SET Price = ? WHERE WaifuId = ?
            """, (new_price, waifu_id))
            await db.commit()

    async def set_waifu_affinity(self, waifu_id: int, affinity_id: int):
        """Set waifu affinity"""
        async with self.db._get_connection() as db:
            await db.execute("""
                UPDATE WaifuInfo SET Affinity = ? WHERE WaifuId = ?
            """, (affinity_id, waifu_id))
            await db.commit()

    async def get_waifu_affinity(self, waifu_id: int):
        """Get waifu affinity"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT Affinity FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_waifu_leaderboard(self, limit: int = 10):
        """Get waifu leaderboard by price"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT WaifuId, ClaimerId, Price FROM WaifuInfo
                WHERE ClaimerId IS NOT NULL
                ORDER BY Price DESC LIMIT ?
            """, (limit,))
            return await cursor.fetchall()

    async def add_waifu_item(self, waifu_id: int, name: str, emoji: str):
        """Add item to waifu"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT INTO WaifuItem (WaifuInfoId, Name, ItemEmoji, DateAdded)
                VALUES (?, ?, ?, datetime('now'))
            """, (waifu_id, name, emoji))
            await db.commit()

    async def get_waifu_items(self, waifu_id: int):
        """Get waifu items"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Name, ItemEmoji FROM WaifuItem WHERE WaifuInfoId = ?
                ORDER BY DateAdded DESC
            """, (waifu_id,))
            return await cursor.fetchall()

    async def get_waifu_history(self, waifu_id: int, limit: int = 10):
        """Get waifu transaction history"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT OldId, NewId, UpdateType, DateAdded
                FROM WaifuUpdate WHERE UserId = ?
                ORDER BY DateAdded DESC LIMIT ?
            """, (waifu_id, limit))
            return await cursor.fetchall()
