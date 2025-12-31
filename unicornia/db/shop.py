from typing import Optional, List, Tuple

class ShopRepository:
    """Repository for Shop system database operations"""
    
    def __init__(self, db):
        self.db = db

    # Shop item type constants
    SHOP_TYPE_ROLE = 0
    SHOP_TYPE_EFFECT = 2
    SHOP_TYPE_OTHER = 3
    SHOP_TYPE_ITEM = 4

    # Shop Entry Methods
    async def get_shop_entries(self, guild_id: int) -> List[Tuple]:
        """Get all shop entries for a guild.
        
        Args:
            guild_id: Discord guild ID.
            
        Returns:
            List of shop entry tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command
                FROM ShopEntry WHERE GuildId = ? ORDER BY `Index`
            """, (guild_id,))
            return await cursor.fetchall()

    async def get_shop_entries_with_items(self, guild_id: int) -> List[Tuple]:
        """Get all shop entries with their items for a guild (Optimized N+1).
        
        Args:
            guild_id: Discord guild ID.
            
        Returns:
            List of shop entry tuples with joined item data.
        """
        async with self.db._get_connection() as db:
            query = """
                SELECT
                    se.Id, se.`Index`, se.Price, se.Name, se.AuthorId, se.Type,
                    se.RoleName, se.RoleId, se.RoleRequirement, se.Command,
                    sei.Id, sei.Text
                FROM ShopEntry se
                LEFT JOIN ShopEntryItem sei ON se.Id = sei.ShopEntryId
                WHERE se.GuildId = ?
                ORDER BY se.`Index`
            """
            cursor = await db.execute(query, (guild_id,))
            return await cursor.fetchall()

    async def get_shop_entry(self, guild_id: int, entry_id: int) -> Optional[Tuple]:
        """Get a specific shop entry.
        
        Args:
            guild_id: Discord guild ID.
            entry_id: Shop entry ID.
            
        Returns:
            Shop entry tuple or None if not found.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command
                FROM ShopEntry WHERE GuildId = ? AND Id = ?
            """, (guild_id, entry_id))
            return await cursor.fetchone()

    async def get_shop_entry_by_index(self, guild_id: int, index: int) -> Optional[Tuple]:
        """Get a specific shop entry by its index.
        
        Args:
            guild_id: Discord guild ID.
            index: Shop entry index.
            
        Returns:
            Shop entry tuple or None if not found.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command
                FROM ShopEntry WHERE GuildId = ? AND `Index` = ?
            """, (guild_id, index))
            return await cursor.fetchone()

    async def add_shop_entry(self, guild_id: int, index: int, price: int, name: str, author_id: int,
                           entry_type: int, role_name: str = None, role_id: int = None,
                           role_requirement: int = None, command: str = None) -> int:
        """Add a new shop entry.
        
        Args:
            guild_id: Discord guild ID.
            index: Display index.
            price: Item price.
            name: Item name.
            author_id: ID of the creator.
            entry_type: Item type ID.
            role_name: Name of role (optional).
            role_id: ID of role (optional).
            role_requirement: ID of required role (optional).
            command: Command string (optional).
            
        Returns:
            ID of the new shop entry.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                INSERT INTO ShopEntry (GuildId, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, index, price, name, author_id, entry_type, role_name, role_id, role_requirement, command))
            await db.commit()
            return cursor.lastrowid

    async def update_shop_entry(self, guild_id: int, entry_id: int, price: int = None, name: str = None,
                              entry_type: int = None, role_name: str = None, role_id: int = None,
                              role_requirement: int = None, command: str = None) -> bool:
        """Update a shop entry.
        
        Args:
            guild_id: Discord guild ID.
            entry_id: Shop entry ID.
            price: New price (optional).
            name: New name (optional).
            entry_type: New type (optional).
            role_name: New role name (optional).
            role_id: New role ID (optional).
            role_requirement: New role requirement (optional).
            command: New command (optional).
            
        Returns:
            True if updated, False if no changes made.
        """
        async with self.db._get_connection() as db:
            
            # Build dynamic update query
            updates = []
            params = []
            
            if price is not None:
                updates.append("Price = ?")
                params.append(price)
            if name is not None:
                updates.append("Name = ?")
                params.append(name)
            if entry_type is not None:
                updates.append("Type = ?")
                params.append(entry_type)
            if role_name is not None:
                updates.append("RoleName = ?")
                params.append(role_name)
            if role_id is not None:
                updates.append("RoleId = ?")
                params.append(role_id)
            if role_requirement is not None:
                updates.append("RoleRequirement = ?")
                params.append(role_requirement)
            if command is not None:
                updates.append("Command = ?")
                params.append(command)
            
            if not updates:
                return False
            
            params.extend([guild_id, entry_id])
            query = f"UPDATE ShopEntry SET {', '.join(updates)} WHERE GuildId = ? AND Id = ?"
            
            await db.execute(query, params)
            await db.commit()
            return True

    async def delete_shop_entry(self, guild_id: int, entry_id: int) -> bool:
        """Delete a shop entry.
        
        Args:
            guild_id: Discord guild ID.
            entry_id: Shop entry ID.
            
        Returns:
            True if deleted, False otherwise.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                DELETE FROM ShopEntry WHERE GuildId = ? AND Id = ?
            """, (guild_id, entry_id))
            await db.commit()
            return cursor.rowcount > 0

    async def get_shop_entry_items(self, entry_id: int) -> List[Tuple[int, str]]:
        """Get items for a shop entry.
        
        Args:
            entry_id: Shop entry ID.
            
        Returns:
            List of (Id, Text) tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, Text FROM ShopEntryItem WHERE ShopEntryId = ?
            """, (entry_id,))
            return await cursor.fetchall()

    async def add_shop_entry_item(self, entry_id: int, text: str) -> None:
        """Add an item to a shop entry.
        
        Args:
            entry_id: Shop entry ID.
            text: Item text.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT INTO ShopEntryItem (ShopEntryId, Text) VALUES (?, ?)
            """, (entry_id, text))
            await db.commit()

    async def delete_shop_entry_item(self, item_id: int) -> None:
        """Delete a shop entry item.
        
        Args:
            item_id: Shop entry item ID.
        """
        async with self.db._get_connection() as db:
            await db.execute("""
                DELETE FROM ShopEntryItem WHERE Id = ?
            """, (item_id,))
            await db.commit()

    async def purchase_shop_item(self, user_id: int, guild_id: int, entry_id: int) -> Tuple[bool, str]:
        """Purchase a shop item.
        
        Args:
            user_id: Discord user ID.
            guild_id: Discord guild ID.
            entry_id: Shop entry ID.
            
        Returns:
            Tuple containing success boolean and status message.
        """
        async with self.db._get_connection() as db:
            
            # Get shop entry
            entry = await self.get_shop_entry(guild_id, entry_id)
            if not entry:
                return False, "Shop item not found"
            
            entry_id, index, price, name, author_id, entry_type, role_name, role_id, role_requirement, command = entry
            
            # Check if user has enough currency
            user_balance = await self.db.economy.get_user_currency(user_id)
            if user_balance < price:
                return False, f"Insufficient currency. You need {price:,} but have {user_balance:,}"
            
            # Check if user already owns this item (for role items)
            if entry_type == 0:  # Role item
                # Check if user already has the role
                # This would need to be checked in the main cog with Discord API
                pass
            
            # Deduct currency (Atomic check via remove_currency)
            if price > 0:
                success = await self.db.economy.remove_currency(user_id, price, "shop_purchase", str(entry_id), note=f"Purchased: {name}")
                
                if not success:
                    return False, f"Insufficient currency or transaction failed."
            
            # Transaction already logged in remove_currency
            
            return True, f"Successfully purchased {name} for {price:,} currency"

    # Inventory Methods
    async def get_user_inventory(self, guild_id: int, user_id: int) -> List[Tuple]:
        """Get a user's inventory for a guild.
        
        Args:
            guild_id: Discord guild ID.
            user_id: Discord user ID.
            
        Returns:
            List of inventory item tuples.
        """
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT
                    ui.ShopEntryId, ui.Quantity,
                    se.`Index`, se.Name, se.Price, se.Type
                FROM UserInventory ui
                JOIN ShopEntry se ON ui.ShopEntryId = se.Id
                WHERE ui.GuildId = ? AND ui.UserId = ?
                ORDER BY se.`Index`
            """, (guild_id, user_id))
            return await cursor.fetchall()

    async def add_inventory_item(self, guild_id: int, user_id: int, entry_id: int, quantity: int = 1):
        """Add an item to user's inventory (Stacking)"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT INTO UserInventory (UserId, GuildId, ShopEntryId, Quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(UserId, GuildId, ShopEntryId)
                DO UPDATE SET Quantity = Quantity + excluded.Quantity
            """, (user_id, guild_id, entry_id, quantity))
            await db.commit()

    async def remove_inventory_item(self, guild_id: int, user_id: int, entry_id: int, quantity: int = 1) -> bool:
        """Remove an item from user's inventory"""
        async with self.db._get_connection() as db:
            # Check current quantity
            cursor = await db.execute("""
                SELECT Quantity FROM UserInventory
                WHERE UserId = ? AND GuildId = ? AND ShopEntryId = ?
            """, (user_id, guild_id, entry_id))
            row = await cursor.fetchone()
            
            if not row or row[0] < quantity:
                return False
            
            new_quantity = row[0] - quantity
            
            if new_quantity > 0:
                await db.execute("""
                    UPDATE UserInventory SET Quantity = ?
                    WHERE UserId = ? AND GuildId = ? AND ShopEntryId = ?
                """, (new_quantity, user_id, guild_id, entry_id))
            else:
                await db.execute("""
                    DELETE FROM UserInventory
                    WHERE UserId = ? AND GuildId = ? AND ShopEntryId = ?
                """, (user_id, guild_id, entry_id))
            
            await db.commit()
            return True
            
    async def get_user_item_count(self, guild_id: int, user_id: int, entry_id: int) -> int:
        """Get how many of an item a user has"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Quantity FROM UserInventory
                WHERE UserId = ? AND GuildId = ? AND ShopEntryId = ?
            """, (user_id, guild_id, entry_id))
            row = await cursor.fetchone()
            return row[0] if row else 0
