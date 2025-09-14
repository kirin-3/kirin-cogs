"""
Shop system for Unicornia - handles role and command items
"""

import discord
from typing import Optional, List, Dict, Any, Tuple
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_number
from .database import DatabaseManager


class ShopSystem:
    """Handles shop items, purchases, and management"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
    
    async def get_shop_items(self, guild_id: int) -> List[Dict[str, Any]]:
        """Get all shop items for a guild"""
        entries = await self.db.get_shop_entries(guild_id)
        items = []
        
        for entry in entries:
            entry_id, index, price, name, author_id, entry_type, role_name, role_id, role_requirement, command = entry
            
            # Get additional items for this entry
            additional_items = await self.db.get_shop_entry_items(entry_id)
            
            item = {
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
            items.append(item)
        
        return items
    
    async def get_shop_item(self, guild_id: int, item_id: int) -> Optional[Dict[str, Any]]:
        """Get a specific shop item"""
        entry = await self.db.get_shop_entry(guild_id, item_id)
        if not entry:
            return None
        
        entry_id, index, price, name, author_id, entry_type, role_name, role_id, role_requirement, command = entry
        additional_items = await self.db.get_shop_entry_items(entry_id)
        
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
        """Purchase a shop item"""
        item = await self.get_shop_item(guild_id, item_id)
        if not item:
            return False, "Shop item not found"
        
        # Check if user has enough currency
        user_balance = await self.db.get_user_currency(user.id)
        if user_balance < item['price']:
            return False, f"Insufficient currency. You need {item['price']:,} but have {user_balance:,}"
        
        # Handle different item types
        if item['type'] == self.db.SHOP_TYPE_ROLE:
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
        
        elif item['type'] == self.db.SHOP_TYPE_COMMAND:
            # Command item - this would need special handling
            # For now, just log the purchase
            pass
        
        # Deduct currency
        success, message = await self.db.purchase_shop_item(user.id, guild_id, item_id)
        if not success:
            return False, message
        
        return True, f"Successfully purchased {item['name']} for {item['price']:,} currency"
    
    async def add_shop_item(self, guild_id: int, index: int, price: int, name: str, author_id: int,
                          item_type: int, role_name: str = None, role_id: int = None,
                          role_requirement: int = None, command: str = None) -> int:
        """Add a new shop item"""
        return await self.db.add_shop_entry(
            guild_id, index, price, name, author_id, item_type,
            role_name, role_id, role_requirement, command
        )
    
    async def update_shop_item(self, guild_id: int, item_id: int, **kwargs) -> bool:
        """Update a shop item"""
        return await self.db.update_shop_entry(guild_id, item_id, **kwargs)
    
    async def delete_shop_item(self, guild_id: int, item_id: int) -> bool:
        """Delete a shop item"""
        return await self.db.delete_shop_entry(guild_id, item_id)
    
    def get_type_name(self, item_type: int) -> str:
        """Get human-readable type name"""
        type_names = {
            self.db.SHOP_TYPE_ROLE: "Role",
            self.db.SHOP_TYPE_COMMAND: "Command",
            self.db.SHOP_TYPE_EFFECT: "Effect",
            self.db.SHOP_TYPE_OTHER: "Other"
        }
        return type_names.get(item_type, "Unknown")
    
    def get_type_emoji(self, item_type: int) -> str:
        """Get emoji for item type"""
        type_emojis = {
            self.db.SHOP_TYPE_ROLE: "🎭",
            self.db.SHOP_TYPE_COMMAND: "⚡",
            self.db.SHOP_TYPE_EFFECT: "✨",
            self.db.SHOP_TYPE_OTHER: "📦"
        }
        return type_emojis.get(item_type, "❓")
