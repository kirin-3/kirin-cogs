"""
Shop system for Unicornia - handles role and command items
"""

import discord
from typing import Optional, List, Tuple
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_number
from ..database import DatabaseManager
from ..types import ShopItem, UserInventoryItem


class ShopSystem:
    """Handles shop items, purchases, and management"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
    
    async def get_shop_items(self, guild_id: int) -> List[ShopItem]:
        """Get all shop items for a guild.
        
        Args:
            guild_id: Discord guild ID.
            
        Returns:
            List of ShopItem objects.
        """
        # Use optimized query to fetch everything in one go
        rows = await self.db.shop.get_shop_entries_with_items(guild_id)
        
        items_map = {}
        
        for row in rows:
            # row: 0=Id, 1=Index, 2=Price, 3=Name, 4=AuthorId, 5=Type,
            #      6=RoleName, 7=RoleId, 8=RoleRequirement, 9=Command,
            #      10=ItemId, 11=ItemText
            entry_id = row[0]
            
            if entry_id not in items_map:
                items_map[entry_id] = {
                    'id': entry_id,
                    'index': row[1],
                    'price': row[2],
                    'name': row[3],
                    'author_id': row[4],
                    'type': row[5],
                    'role_name': row[6],
                    'role_id': row[7],
                    'role_requirement': row[8],
                    'command': row[9],
                    'additional_items': []
                }
            
            # If there's an associated item (ItemId is not None)
            if row[10] is not None:
                items_map[entry_id]['additional_items'].append((row[10], row[11]))
        
        # Convert map to list and sort by index
        items = list(items_map.values())
        items.sort(key=lambda x: x['index'])
        
        return items
    
    async def get_shop_item(self, guild_id: int, item_id: int) -> Optional[ShopItem]:
        """Get a specific shop item (by Index or ID).
        
        Args:
            guild_id: Discord guild ID.
            item_id: Item ID or Index.
            
        Returns:
            ShopItem object or None.
        """
        # Try by Index first
        entry = await self.db.shop.get_shop_entry_by_index(guild_id, item_id)
        
        # If not found, try by ID
        if not entry:
            entry = await self.db.shop.get_shop_entry(guild_id, item_id)
            
        if not entry:
            return None
        
        entry_id, index, price, name, author_id, entry_type, role_name, role_id, role_requirement, command = entry
        additional_items = await self.db.shop.get_shop_entry_items(entry_id)
        
        return {
            'id': entry_id,
            'index': index,
            'price': price,
            'name': name,
            'author_id': author_id,
            'type': entry_type,
            'role_name': role_name,
            'role_id': role_id,
            'role_requirement': role_requirement,
            'command': command,
            'additional_items': additional_items
        }
    
    async def purchase_item(self, user: discord.Member, guild_id: int, item_id: int) -> Tuple[bool, str]:
        """Purchase a shop item.
        
        Args:
            user: Discord member.
            guild_id: Guild ID.
            item_id: Item ID.
            
        Returns:
            Tuple of (success, message).
        """
        item = await self.get_shop_item(guild_id, item_id)
        if not item:
            return False, "Shop item not found"
        
        # Check if user has enough currency
        user_balance = await self.db.economy.get_user_currency(user.id)
        if user_balance < item['price']:
            return False, f"Insufficient Slut points. You need {item['price']:,} but have {user_balance:,}"
        
        # Handle different item types
        if item['type'] == self.db.shop.SHOP_TYPE_ROLE:
            # Role item
            if item['role_id']:
                role = user.guild.get_role(item['role_id'])
                if not role:
                    return False, "Role no longer exists"
                
                if role in user.roles:
                    return False, "You already have this role"
                
                # Check role requirements
                if item['role_requirement']:
                    required_role = user.guild.get_role(item['role_requirement'])
                    if required_role and required_role not in user.roles:
                        return False, f"You need the {required_role.name} role to purchase this item"
                
                # Add role
                try:
                    await user.add_roles(role, reason=f"Shop purchase: {item['name']}")
                except discord.Forbidden:
                    return False, "I don't have permission to assign this role"
                except discord.HTTPException:
                    return False, "Failed to assign role"
        
        elif item['type'] == self.db.shop.SHOP_TYPE_ITEM:
            # Regular item - just inventory tracking
            pass
        
        # Deduct currency
        # Use the actual ID from the item (in case we found it by index)
        success, message = await self.db.shop.purchase_shop_item(user.id, guild_id, item['id'])
        if not success:
            return False, message
            
        # If purchase successful, add to inventory if it's an ITEM type
        if item['type'] == self.db.shop.SHOP_TYPE_ITEM:
            await self.db.shop.add_inventory_item(guild_id, user.id, item['id'], 1)
        
        return True, f"Successfully purchased {item['name']} for {item['price']:,} Slut points"
    
    async def add_shop_item(self, guild_id: int, index: int, price: int, name: str, author_id: int,
                          item_type: int, role_name: str = None, role_id: int = None,
                          role_requirement: int = None, command: str = None) -> int:
        """Add a new shop item.
        
        Args:
            guild_id: Guild ID.
            index: Display index.
            price: Price.
            name: Name.
            author_id: Creator ID.
            item_type: Type ID.
            role_name: Role name.
            role_id: Role ID.
            role_requirement: Role requirement ID.
            command: Command string (Deprecated).
            
        Returns:
            New item ID.
        """
        return await self.db.shop.add_shop_entry(
            guild_id, index, price, name, author_id, item_type,
            role_name, role_id, role_requirement, command
        )
    
    async def update_shop_item(self, guild_id: int, item_id: int, **kwargs) -> bool:
        """Update a shop item.
        
        Args:
            guild_id: Guild ID.
            item_id: Item ID.
            **kwargs: Fields to update.
            
        Returns:
            Success boolean.
        """
        return await self.db.shop.update_shop_entry(guild_id, item_id, **kwargs)
    
    async def delete_shop_item(self, guild_id: int, item_id: int) -> bool:
        """Delete a shop item.
        
        Args:
            guild_id: Guild ID.
            item_id: Item ID.
            
        Returns:
            Success boolean.
        """
        return await self.db.shop.delete_shop_entry(guild_id, item_id)
    
    def get_type_name(self, item_type: int) -> str:
        """Get human-readable type name.
        
        Args:
            item_type: Type ID.
            
        Returns:
            Type name string.
        """
        type_names = {
            self.db.shop.SHOP_TYPE_ROLE: "Role",
            self.db.shop.SHOP_TYPE_EFFECT: "Effect",
            self.db.shop.SHOP_TYPE_OTHER: "Other",
            self.db.shop.SHOP_TYPE_ITEM: "Item"
        }
        return type_names.get(item_type, "Unknown")
    
    def get_type_emoji(self, item_type: int) -> str:
        """Get emoji for item type.
        
        Args:
            item_type: Type ID.
            
        Returns:
            Emoji string.
        """
        type_emojis = {
            self.db.shop.SHOP_TYPE_ROLE: "🎭",
            self.db.shop.SHOP_TYPE_EFFECT: "✨",
            self.db.shop.SHOP_TYPE_OTHER: "📦",
            self.db.shop.SHOP_TYPE_ITEM: "🎒"
        }
        return type_emojis.get(item_type, "❓")

    async def get_user_inventory(self, guild_id: int, user_id: int) -> List[UserInventoryItem]:
        """Get a user's inventory items.
        
        Args:
            guild_id: Guild ID.
            user_id: User ID.
            
        Returns:
            List of UserInventoryItem objects.
        """
        rows = await self.db.shop.get_user_inventory(guild_id, user_id)
        
        inventory = []
        for row in rows:
            # row: ShopEntryId, Quantity, Index, Name, Price, Type
            inventory.append({
                'id': row[0],
                'quantity': row[1],
                'index': row[2],
                'name': row[3],
                'price': row[4],
                'type': row[5]
            })
            
        return inventory