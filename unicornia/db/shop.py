from typing import List, Dict, Any, Tuple

class ShopRepository:
    """Repository for Shop system database operations"""
    
    def __init__(self, db):
        self.db = db

    # Shop item type constants
    SHOP_TYPE_ROLE = 0
    SHOP_TYPE_COMMAND = 1
    SHOP_TYPE_EFFECT = 2
    SHOP_TYPE_OTHER = 3

    # Shop Entry Methods
    async def get_shop_entries(self, guild_id: int):
        """Get all shop entries for a guild"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command
                FROM ShopEntry WHERE GuildId = ? ORDER BY `Index`
            """, (guild_id,))
            return await cursor.fetchall()

    async def get_shop_entry(self, guild_id: int, entry_id: int):
        """Get a specific shop entry"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command
                FROM ShopEntry WHERE GuildId = ? AND Id = ?
            """, (guild_id, entry_id))
            return await cursor.fetchone()

    async def get_shop_entry_by_index(self, guild_id: int, index: int):
        """Get a specific shop entry by its index"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command
                FROM ShopEntry WHERE GuildId = ? AND `Index` = ?
            """, (guild_id, index))
            return await cursor.fetchone()

    async def add_shop_entry(self, guild_id: int, index: int, price: int, name: str, author_id: int,
                           entry_type: int, role_name: str = None, role_id: int = None,
                           role_requirement: int = None, command: str = None):
        """Add a new shop entry"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                INSERT INTO ShopEntry (GuildId, `Index`, Price, Name, AuthorId, Type, RoleName, RoleId, RoleRequirement, Command)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, index, price, name, author_id, entry_type, role_name, role_id, role_requirement, command))
            await db.commit()
            return cursor.lastrowid

    async def update_shop_entry(self, guild_id: int, entry_id: int, price: int = None, name: str = None,
                              entry_type: int = None, role_name: str = None, role_id: int = None,
                              role_requirement: int = None, command: str = None):
        """Update a shop entry"""
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

    async def delete_shop_entry(self, guild_id: int, entry_id: int):
        """Delete a shop entry"""
        async with self.db._get_connection() as db:
            await db.execute("""
                DELETE FROM ShopEntry WHERE GuildId = ? AND Id = ?
            """, (guild_id, entry_id))
            await db.commit()
            return True

    async def get_shop_entry_items(self, entry_id: int):
        """Get items for a shop entry"""
        async with self.db._get_connection() as db:
            cursor = await db.execute("""
                SELECT Id, Text FROM ShopEntryItem WHERE ShopEntryId = ?
            """, (entry_id,))
            return await cursor.fetchall()

    async def add_shop_entry_item(self, entry_id: int, text: str):
        """Add an item to a shop entry"""
        async with self.db._get_connection() as db:
            await db.execute("""
                INSERT INTO ShopEntryItem (ShopEntryId, Text) VALUES (?, ?)
            """, (entry_id, text))
            await db.commit()

    async def delete_shop_entry_item(self, item_id: int):
        """Delete a shop entry item"""
        async with self.db._get_connection() as db:
            await db.execute("""
                DELETE FROM ShopEntryItem WHERE Id = ?
            """, (item_id,))
            await db.commit()

    async def purchase_shop_item(self, user_id: int, guild_id: int, entry_id: int) -> tuple[bool, str]:
        """Purchase a shop item"""
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
            success = await self.db.economy.remove_currency(user_id, price, "shop_purchase", str(entry_id), note=f"Purchased: {name}")
            
            if not success:
                return False, f"Insufficient currency or transaction failed."
            
            # Transaction already logged in remove_currency
            
            return True, f"Successfully purchased {name} for {price:,} currency"
