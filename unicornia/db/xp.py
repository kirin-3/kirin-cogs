from typing import List, Dict, Any, Tuple

class XPRepository:
    """Repository for XP system database operations"""
    
    def __init__(self, db):
        self.db = db

    # XP methods
    async def get_user_xp(self, user_id: int, guild_id: int) -> int:
        """Get user's XP in a guild.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            
        Returns:
            int: The user's XP amount, or 0 if not found.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT Xp FROM UserXpStats WHERE UserId = ? AND GuildId = ?", (user_id, guild_id))
            row = await cursor.fetchone()
            return row[0] if row else 0
            
    async def get_all_user_xp(self, user_id: int) -> list[tuple[int, int]]:
        """Get user's XP across all guilds.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            list[tuple[int, int]]: A list of (GuildId, XP) tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("SELECT GuildId, Xp FROM UserXpStats WHERE UserId = ?", (user_id,))
            return await cursor.fetchall()
    
    async def add_xp(self, user_id: int, guild_id: int, amount: int) -> None:
        """Add XP to user in a guild.
        
        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            amount: Amount of XP to add
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT INTO UserXpStats (UserId, GuildId, Xp) VALUES (?, ?, ?)
                ON CONFLICT(UserId, GuildId) DO UPDATE SET Xp = Xp + ?
            """, (user_id, guild_id, amount, amount))
            
            # Update total XP
            await db.execute("""
                INSERT INTO DiscordUser (UserId, TotalXp) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET TotalXp = TotalXp + ?
            """, (user_id, amount, amount))
            
            await db.commit()

    async def add_xp_bulk(self, updates: List[Tuple[int, int, int]]):
        """Add XP to multiple users in bulk
        
        Args:
            updates: List of (user_id, guild_id, amount) tuples
        """
        if not updates:
            return
            
        async with self.db._get_connection() as db:
            
            # Prepare params for UserXpStats: (user_id, guild_id, amount, amount)
            xp_stats_params = [(u, g, a, a) for u, g, a in updates]
            
            # Prepare params for DiscordUser: (user_id, amount, amount)
            user_params = [(u, a, a) for u, g, a in updates]
            
            await db.executemany("""
                INSERT INTO UserXpStats (UserId, GuildId, Xp) VALUES (?, ?, ?)
                ON CONFLICT(UserId, GuildId) DO UPDATE SET Xp = Xp + ?
            """, xp_stats_params)
            
            await db.executemany("""
                INSERT INTO DiscordUser (UserId, TotalXp) VALUES (?, ?)
                ON CONFLICT(UserId) DO UPDATE SET TotalXp = TotalXp + ?
            """, user_params)
            
            await db.commit()

    # XP Settings Methods
    async def get_xp_settings(self, guild_id: int):
        """Get XP settings for guild"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT XpRateMultiplier, XpPerMessage, XpMinutesTimeout FROM XpSettings WHERE GuildId = ?
            """, (guild_id,))
            result = await cursor.fetchone()
            
            if not result:
                # Create default settings
                await db.execute("""
                    INSERT INTO XpSettings (GuildId, XpRateMultiplier, XpPerMessage, XpMinutesTimeout) 
                    VALUES (?, 1.0, 3, 5)
                """, (guild_id,))
                await db.commit()
                return (1.0, 3, 5)
            
            return result

    # XP Role Rewards Methods
    async def get_xp_role_rewards(self, guild_id: int, level: int):
        """Get role rewards for a specific level"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT RoleId, Remove FROM XpRoleReward WHERE GuildId = ? AND Level = ?
            """, (guild_id, level))
            return await cursor.fetchall()

    async def get_all_xp_role_rewards(self, guild_id: int):
        """Get all role rewards for a guild"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Level, RoleId, Remove FROM XpRoleReward WHERE GuildId = ? ORDER BY Level ASC
            """, (guild_id,))
            return await cursor.fetchall()

    async def add_xp_role_reward(self, guild_id: int, level: int, role_id: int, remove: bool = False):
        """Add XP role reward"""
        async with self.db._get_connection() as db:
            # Prevent duplicates
            cursor = await db.execute("SELECT Id FROM XpRoleReward WHERE GuildId = ? AND Level = ? AND RoleId = ?", (guild_id, level, role_id))
            if not await cursor.fetchone():
                await db.execute("""
                    INSERT INTO XpRoleReward (GuildId, Level, RoleId, Remove) VALUES (?, ?, ?, ?)
                """, (guild_id, level, role_id, remove))
                await db.commit()

    async def remove_xp_role_reward(self, guild_id: int, level: int, role_id: int):
        """Remove XP role reward"""
        async with self.db._get_connection() as db:
            await db.execute("DELETE FROM XpRoleReward WHERE GuildId = ? AND Level = ? AND RoleId = ?", (guild_id, level, role_id))
            await db.commit()


    # XP currency reward methods
    async def get_xp_currency_rewards(self, guild_id: int):
        """Get XP currency rewards for a guild (XpSettingsId is GuildId)"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Level, Amount FROM XpCurrencyReward WHERE XpSettingsId = ? ORDER BY Level ASC
            """, (guild_id,))
            return await cursor.fetchall()
    
    async def add_xp_currency_reward(self, guild_id: int, level: int, amount: int):
        """Add or update an XP currency reward"""
        async with self.db._get_connection() as db:
            # Check if exists
            cursor = await db.execute("SELECT Id FROM XpCurrencyReward WHERE XpSettingsId = ? AND Level = ?", (guild_id, level))
            existing = await cursor.fetchone()
            
            if amount <= 0:
                if existing:
                    await db.execute("DELETE FROM XpCurrencyReward WHERE Id = ?", (existing[0],))
            else:
                if existing:
                    await db.execute("UPDATE XpCurrencyReward SET Amount = ? WHERE Id = ?", (amount, existing[0]))
                else:
                    await db.execute("""
                        INSERT INTO XpCurrencyReward (XpSettingsId, Level, Amount) VALUES (?, ?, ?)
                    """, (guild_id, level, amount))
            
            await db.commit()

    # XP Shop methods
    async def get_user_xp_items(self, user_id: int, item_type: int = None):
        """Get user's owned XP shop items"""
        async with self.db._get_connection() as db:
            
            # Ensure user has default background (free for everyone)
            if item_type == 1:  # Background type
                await self._ensure_default_background(user_id, db)
            
            if item_type is not None:
                cursor = await db.execute("""
                    SELECT Id, UserId, ItemType, ItemKey FROM XpShopOwnedItem 
                    WHERE UserId = ? AND ItemType = ?
                """, (user_id, item_type))
            else:
                cursor = await db.execute("""
                    SELECT Id, UserId, ItemType, ItemKey FROM XpShopOwnedItem 
                    WHERE UserId = ?
                """, (user_id,))
            return await cursor.fetchall()
    
    async def _ensure_default_background(self, user_id: int, db):
        """Ensure user has the default background and it's set as active if no other is active"""
        # Check if user already has default background
        cursor = await db.execute("""
            SELECT COUNT(*) FROM XpShopOwnedItem 
            WHERE UserId = ? AND ItemType = 1 AND ItemKey = 'default'
        """, (user_id,))
        count = (await cursor.fetchone())[0]
        
        if count == 0:
            # Check if user has any active background
            cursor = await db.execute("""
                SELECT COUNT(*) FROM XpShopOwnedItem 
                WHERE UserId = ? AND ItemType = 1 AND IsUsing = TRUE
            """, (user_id,))
            has_active = (await cursor.fetchone())[0] > 0
            
            # Give user the default background for free and set as active if no other is active
            await db.execute("""
                INSERT INTO XpShopOwnedItem (UserId, ItemType, ItemKey, IsUsing) VALUES (?, 1, 'default', ?)
            """, (user_id, not has_active))
            await db.commit()
    
    async def user_owns_xp_item(self, user_id: int, item_type: int, item_key: str) -> bool:
        """Check if user owns a specific XP shop item"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT COUNT(*) FROM XpShopOwnedItem 
                WHERE UserId = ? AND ItemType = ? AND ItemKey = ?
            """, (user_id, item_type, item_key))
            count = (await cursor.fetchone())[0]
            return count > 0
    
    async def purchase_xp_item(self, user_id: int, item_type: int, item_key: str, price: int) -> bool:
        """Purchase an XP shop item"""
        async with self.db._get_connection() as db:
            
            # Check if user already owns this item
            if await self.user_owns_xp_item(user_id, item_type, item_key):
                return False
            
            # Atomic deduction
            cursor = await db.execute("""
                UPDATE DiscordUser
                SET CurrencyAmount = CurrencyAmount - ?
                WHERE UserId = ? AND CurrencyAmount >= ?
            """, (price, user_id, price))
            
            if cursor.rowcount == 0:
                return False
            
            # Add item to user's collection
            await db.execute("""
                INSERT INTO XpShopOwnedItem (UserId, ItemType, ItemKey, IsUsing) VALUES (?, ?, ?, FALSE)
            """, (user_id, item_type, item_key))
            
            # Log transaction
            await db.execute("""
                INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, Reason, DateAdded)
                VALUES (?, ?, 'xp_shop_purchase', ?, ?, datetime('now'))
            """, (user_id, -price, item_key, f"Purchased XP item: {item_key}"))
            
            await db.commit()
            return True

    async def give_xp_item(self, user_id: int, item_type: int, item_key: str) -> bool:
        """Give an XP shop item to a user without cost"""
        async with self.db._get_connection() as db:
            
            # Check if user already owns this item
            if await self.user_owns_xp_item(user_id, item_type, item_key):
                return False
            
            # Add item to user's collection
            await db.execute("""
                INSERT INTO XpShopOwnedItem (UserId, ItemType, ItemKey, IsUsing) VALUES (?, ?, ?, FALSE)
            """, (user_id, item_type, item_key))
            
            await db.commit()
            return True
    
    async def get_active_xp_item(self, user_id: int, item_type: int) -> str:
        """Get the user's active XP item of a given type"""
        async with self.db._get_connection() as db:
            
            # Ensure user has default background
            if item_type == 1:  # Background type
                await self._ensure_default_background(user_id, db)
            
            cursor = await db.execute("""
                SELECT ItemKey FROM XpShopOwnedItem 
                WHERE UserId = ? AND ItemType = ? AND IsUsing = TRUE
            """, (user_id, item_type))
            result = await cursor.fetchone()
            
            if result:
                return result[0]
            
            # If no active item, return default
            return "default"
    
    async def set_active_xp_item(self, user_id: int, item_type: int, item_key: str) -> bool:
        """Set an XP item as active (user must own it first)"""
        async with self.db._get_connection() as db:
            
            # Check if user owns the item
            if not await self.user_owns_xp_item(user_id, item_type, item_key):
                return False
            
            # Set all items of this type to not using
            await db.execute("""
                UPDATE XpShopOwnedItem 
                SET IsUsing = FALSE 
                WHERE UserId = ? AND ItemType = ?
            """, (user_id, item_type))
            
            # Set the specified item as using
            await db.execute("""
                UPDATE XpShopOwnedItem 
                SET IsUsing = TRUE 
                WHERE UserId = ? AND ItemType = ? AND ItemKey = ?
            """, (user_id, item_type, item_key))
            
            await db.commit()
            return True
    
    async def get_user_rank_in_guild(self, user_id: int, guild_id: int) -> int:
        """Get user's XP rank in a guild"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT COUNT(*) + 1 FROM UserXpStats 
                WHERE GuildId = ? AND Xp > (
                    SELECT COALESCE(Xp, 0) FROM UserXpStats 
                    WHERE UserId = ? AND GuildId = ?
                )
            """, (guild_id, user_id, guild_id))
            rank = (await cursor.fetchone())[0]
            return rank

    async def get_top_xp_users(self, guild_id: int, limit: int = 10, offset: int = 0):
        """Get top XP users in a guild"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT UserId, Xp FROM UserXpStats
                WHERE GuildId = ?
                ORDER BY Xp DESC
                LIMIT ? OFFSET ?
            """, (guild_id, limit, offset))
            return await cursor.fetchall()

    async def get_all_guild_xp(self, guild_id: int):
        """Get all XP users in a guild for filtering"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT UserId, Xp FROM UserXpStats
                WHERE GuildId = ?
                ORDER BY Xp DESC
            """, (guild_id,))
            return await cursor.fetchall()
