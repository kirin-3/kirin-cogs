from typing import List, Tuple, Optional

class WaifuRepository:
    """Repository for Waifu system database operations"""
    
    def __init__(self, db):
        self.db = db

    # Waifu System Methods
    async def get_waifu_info(self, waifu_id: int) -> Optional[Tuple]:
        """Get waifu information.
        
        Args:
            waifu_id: Discord user ID.
            
        Returns:
            Tuple with waifu info or None.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT WaifuId, ClaimerId, Price, Affinity, DateAdded FROM WaifuInfo WHERE WaifuId = ?
            """, (waifu_id,))
            return await cursor.fetchone()

    async def claim_waifu(self, waifu_id: int, claimer_id: int, price: int) -> bool:
        """Claim a waifu.
        
        Args:
            waifu_id: Waifu user ID.
            claimer_id: Claimer user ID.
            price: Claim price.
            
        Returns:
            Success boolean.
        """
        async with self.db._get_connection() as db:
            # Atomic insert-or-claim-if-unowned
            cursor = await db.execute("""
                INSERT INTO WaifuInfo (WaifuId, ClaimerId, Price, DateAdded)
                VALUES (?, ?, ?, datetime('now'))
                ON CONFLICT(WaifuId) DO UPDATE SET
                    ClaimerId = excluded.ClaimerId,
                    Price = excluded.Price,
                    DateAdded = excluded.DateAdded
                WHERE WaifuInfo.ClaimerId IS NULL
            """, (waifu_id, claimer_id, price))
            
            if cursor.rowcount == 0:
                return False  # Already claimed
            
            # Log waifu update (Claimed = 0)
            await db.execute("""
                INSERT INTO WaifuUpdates (UserId, OldId, NewId, UpdateType, DateAdded)
                VALUES (?, ?, ?, 0, datetime('now'))
            """, (waifu_id, 0, claimer_id))
            
            await db.commit()
            return True

    async def divorce_waifu(self, waifu_id: int, claimer_id: int) -> bool:
        """Divorce a waifu.
        
        Args:
            waifu_id: Waifu user ID.
            claimer_id: Claimer user ID.
            
        Returns:
            Success boolean.
        """
        async with self.db._get_connection() as db:
            
            # Check if user owns this waifu
            cursor = await db.execute("SELECT ClaimerId FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            
            if not result or result[0] != claimer_id:
                return False  # Not owned by this user
            
            # Log divorce (Divorced = 1) - Note: Nadeko likely uses UserId as the Waifu ID here
            await db.execute("""
                INSERT INTO WaifuUpdates (UserId, OldId, NewId, UpdateType, DateAdded)
                VALUES (?, ?, ?, 1, datetime('now'))
            """, (waifu_id, claimer_id, 0))
            
            # Remove claim
            await db.execute("""
                UPDATE WaifuInfo SET ClaimerId = NULL WHERE WaifuId = ?
            """, (waifu_id,))
            
            await db.commit()
            return True

    async def transfer_waifu(self, waifu_id: int, new_owner_id: int, price: int) -> None:
        """Transfer waifu ownership.
        
        Args:
            waifu_id: Waifu user ID.
            new_owner_id: New owner user ID.
            price: New price.
        """
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
                INSERT INTO WaifuUpdates (UserId, OldId, NewId, UpdateType, DateAdded)
                VALUES (?, ?, ?, 2, datetime('now'))
            """, (waifu_id, old_owner_id, new_owner_id))
            
            await db.commit()

    async def force_claim_waifu(self, waifu_id: int, claimer_id: int, old_owner_id: int, price: int, claimer_note: str, owner_note: str) -> bool:
        """Atomically force claim a waifu: transfer currency and ownership.

        Args:
            waifu_id: Waifu ID.
            claimer_id: New owner ID.
            old_owner_id: Previous owner ID.
            price: Price paid.
            claimer_note: Note for claimer's transaction log.
            owner_note: Note for old owner's transaction log.

        Returns:
            bool: True if successful, False if insufficient funds or other error.
        """
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                # 1. Deduct from claimer
                cursor = await db.execute("""
                    UPDATE DiscordUser
                    SET CurrencyAmount = CurrencyAmount - ?
                    WHERE UserId = ? AND CurrencyAmount >= ?
                """, (price, claimer_id, price))

                if cursor.rowcount == 0:
                    # Insufficient funds
                    await db.execute("ROLLBACK")
                    return False

                # 2. Add to old owner
                await db.execute("""
                    INSERT INTO DiscordUser (UserId, CurrencyAmount) VALUES (?, ?)
                    ON CONFLICT(UserId) DO UPDATE SET CurrencyAmount = CurrencyAmount + ?
                """, (old_owner_id, price, price))

                # 3. Transfer Waifu
                await db.execute("""
                    UPDATE WaifuInfo
                    SET ClaimerId = ?, Price = ?
                    WHERE WaifuId = ?
                """, (claimer_id, price, waifu_id))

                # 4. Logs
                
                # Log claimer transaction
                await db.execute("""
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """, (claimer_id, -price, "waifu_claim", str(waifu_id), None, claimer_note))

                # Log old owner transaction
                await db.execute("""
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """, (old_owner_id, price, "waifu_sold", str(waifu_id), claimer_id, owner_note))

                # Log waifu update
                await db.execute("""
                    INSERT INTO WaifuUpdates (UserId, OldId, NewId, UpdateType, DateAdded)
                    VALUES (?, ?, ?, 2, datetime('now'))
                """, (waifu_id, old_owner_id, claimer_id))

                await db.commit()
                return True

            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def gift_waifu_transaction(self, giver_id: int, waifu_id: int, gift_name: str, gift_emoji: str, gift_price: int, new_waifu_price: int, note: str) -> bool:
        """Atomically gift a waifu: deduct currency, update price, add item.

        Args:
            giver_id: Giver ID.
            waifu_id: Waifu ID.
            gift_name: Gift name.
            gift_emoji: Gift emoji.
            gift_price: Price of gift.
            new_waifu_price: New price of waifu.
            note: Transaction note.
            
        Returns:
            bool: True if successful, False if insufficient funds.
        """
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                # 1. Deduct currency
                cursor = await db.execute("""
                    UPDATE DiscordUser
                    SET CurrencyAmount = CurrencyAmount - ?
                    WHERE UserId = ? AND CurrencyAmount >= ?
                """, (gift_price, giver_id, gift_price))

                if cursor.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return False

                # 2. Update waifu price (Upsert to ensure existence for FK constraint)
                await db.execute("""
                    INSERT INTO WaifuInfo (WaifuId, Price, DateAdded)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(WaifuId) DO UPDATE SET Price = ?
                """, (waifu_id, new_waifu_price, new_waifu_price))

                # 3. Add item
                await db.execute("""
                    INSERT INTO WaifuItem (WaifuInfoId, Name, ItemEmoji, DateAdded)
                    VALUES (?, ?, ?, datetime('now'))
                """, (waifu_id, gift_name, gift_emoji))

                # 4. Log currency transaction
                await db.execute("""
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, Reason, DateAdded)
                    VALUES (?, ?, 'waifu_gift', ?, ?, datetime('now'))
                """, (giver_id, -gift_price, f"Gift {gift_name} to {waifu_id}", note))

                await db.commit()
                return True

            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def claim_waifu_transaction(self, waifu_id: int, claimer_id: int, price: int, note: str) -> bool:
        """Atomically claim a waifu: deduct currency and set owner.

        Args:
            waifu_id: Waifu ID.
            claimer_id: Claimer ID.
            price: Price.
            note: Transaction note.
            
        Returns:
            bool: True if successful, False if insufficient funds or already claimed.
        """
        async with self.db._get_connection() as db:
            await db.execute("BEGIN")
            try:
                # 0. Check if already claimed (Double check inside transaction to be safe)
                cursor = await db.execute("SELECT ClaimerId FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
                result = await cursor.fetchone()
                if result and result[0] is not None:
                    await db.execute("ROLLBACK")
                    return False

                # 1. Deduct currency
                cursor = await db.execute("""
                    UPDATE DiscordUser
                    SET CurrencyAmount = CurrencyAmount - ?
                    WHERE UserId = ? AND CurrencyAmount >= ?
                """, (price, claimer_id, price))

                if cursor.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return False

                # 2. Update Waifu (Upsert to preserve Affinity/DateAdded)
                cursor = await db.execute("""
                    INSERT INTO WaifuInfo (WaifuId, ClaimerId, Price, DateAdded)
                    VALUES (?, ?, ?, datetime('now'))
                    ON CONFLICT(WaifuId) DO UPDATE SET
                        ClaimerId = excluded.ClaimerId,
                        Price = excluded.Price,
                        DateAdded = excluded.DateAdded
                    WHERE WaifuInfo.ClaimerId IS NULL
                """, (waifu_id, claimer_id, price))

                if cursor.rowcount == 0:
                    await db.execute("ROLLBACK")
                    return False

                # 3. Log Waifu
                await db.execute("""
                    INSERT INTO WaifuUpdates (UserId, OldId, NewId, UpdateType, DateAdded)
                    VALUES (?, ?, ?, 0, datetime('now'))
                """, (waifu_id, 0, claimer_id))

                # 4. Log Currency
                await db.execute("""
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, Reason, DateAdded)
                    VALUES (?, ?, 'waifu_claim', ?, ?, datetime('now'))
                """, (claimer_id, -price, str(waifu_id), note))

                await db.commit()
                return True

            except Exception:
                await db.execute("ROLLBACK")
                raise

    async def admin_reset_waifu(self, waifu_id: int) -> bool:
        """Admin reset waifu: remove claimer and set price to 50.
        
        Args:
            waifu_id: Waifu user ID.
            
        Returns:
            Success boolean.
        """
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
                INSERT INTO WaifuUpdates (UserId, OldId, NewId, UpdateType, DateAdded)
                VALUES (?, ?, 0, 99, datetime('now'))
            """, (waifu_id, old_owner_id))
            
            await db.commit()
            return True

    async def get_waifu_owner(self, waifu_id: int) -> Optional[int]:
        """Get waifu owner.
        
        Args:
            waifu_id: Waifu user ID.
            
        Returns:
            Owner ID or None.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT ClaimerId FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_user_waifus(self, user_id: int) -> List[Tuple]:
        """Get all waifus owned by a user.
        
        Args:
            user_id: User ID.
            
        Returns:
            List of waifu tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT WaifuId, Price, Affinity, DateAdded FROM WaifuInfo WHERE ClaimerId = ?
                ORDER BY DateAdded DESC
            """, (user_id,))
            return await cursor.fetchall()

    async def get_waifu_price(self, waifu_id: int) -> int:
        """Get current waifu price.
        
        Args:
            waifu_id: Waifu user ID.
            
        Returns:
            Current price (default 50).
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT Price FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            return result[0] if result else 50  # Default price

    async def update_waifu_price(self, waifu_id: int, new_price: int) -> None:
        """Update waifu price.
        
        Args:
            waifu_id: Waifu user ID.
            new_price: New price.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                UPDATE WaifuInfo SET Price = ? WHERE WaifuId = ?
            """, (new_price, waifu_id))
            await db.commit()

    async def set_waifu_affinity(self, waifu_id: int, affinity_id: int) -> None:
        """Set waifu affinity (updates if exists, inserts if not).
        
        Args:
            waifu_id: Waifu user ID.
            affinity_id: Affinity user ID.
        """
        async with self.db._get_connection() as db:
            # Check if record exists
            cursor = await db.execute("SELECT WaifuId FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            exists = await cursor.fetchone()

            if exists:
                await db.execute("""
                    UPDATE WaifuInfo SET Affinity = ? WHERE WaifuId = ?
                """, (affinity_id, waifu_id))
            else:
                # Insert new record with default price 50, no claimer
                await db.execute("""
                    INSERT INTO WaifuInfo (WaifuId, ClaimerId, Price, Affinity, DateAdded)
                    VALUES (?, NULL, 50, ?, datetime('now'))
                """, (waifu_id, affinity_id))
            
            await db.commit()

    async def get_waifu_affinity(self, waifu_id: int) -> Optional[int]:
        """Get waifu affinity.
        
        Args:
            waifu_id: Waifu user ID.
            
        Returns:
            Affinity user ID or None.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT Affinity FROM WaifuInfo WHERE WaifuId = ?", (waifu_id,))
            result = await cursor.fetchone()
            return result[0] if result else None

    async def get_waifu_leaderboard(self, limit: int = 10) -> List[Tuple]:
        """Get waifu leaderboard by price.
        
        Args:
            limit: Limit results.
            
        Returns:
            List of waifu tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT WaifuId, ClaimerId, Price FROM WaifuInfo
                WHERE ClaimerId IS NOT NULL
                ORDER BY Price DESC LIMIT ?
            """, (limit,))
            return await cursor.fetchall()

    async def add_waifu_item(self, waifu_id: int, name: str, emoji: str) -> None:
        """Add item to waifu.
        
        Args:
            waifu_id: Waifu user ID.
            name: Item name.
            emoji: Item emoji.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT INTO WaifuItem (WaifuInfoId, Name, ItemEmoji, DateAdded)
                VALUES (?, ?, ?, datetime('now'))
            """, (waifu_id, name, emoji))
            await db.commit()

    async def get_waifu_items(self, waifu_id: int) -> List[Tuple]:
        """Get waifu items.
        
        Args:
            waifu_id: Waifu user ID.
            
        Returns:
            List of item tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Name, ItemEmoji FROM WaifuItem WHERE WaifuInfoId = ?
                ORDER BY DateAdded DESC
            """, (waifu_id,))
            return await cursor.fetchall()

    async def get_waifu_gifts_aggregated(self, waifu_id: int) -> List[Tuple]:
        """Get waifu gifts aggregated by count.
        
        Args:
            waifu_id: Waifu user ID.
            
        Returns:
            List of aggregated gift tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Name, ItemEmoji, COUNT(*) as Count
                FROM WaifuItem
                WHERE WaifuInfoId = ?
                GROUP BY Name, ItemEmoji
                ORDER BY Count DESC
            """, (waifu_id,))
            return await cursor.fetchall()

    async def get_affinity_towards(self, user_id: int) -> List[Tuple]:
        """Get list of users who have affinity towards this user.
        
        Args:
            user_id: User ID.
            
        Returns:
            List of waifu ID tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT WaifuId FROM WaifuInfo WHERE Affinity = ?
            """, (user_id,))
            return await cursor.fetchall()

    async def get_waifu_history(self, waifu_id: int, limit: int = 10) -> List[Tuple]:
        """Get waifu transaction history.
        
        Args:
            waifu_id: Waifu user ID.
            limit: Limit results.
            
        Returns:
            List of history tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT OldId, NewId, UpdateType, DateAdded
                FROM WaifuUpdates WHERE UserId = ?
                ORDER BY DateAdded DESC LIMIT ?
            """, (waifu_id, limit))
            return await cursor.fetchall()
