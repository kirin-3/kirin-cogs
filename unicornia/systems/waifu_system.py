"""
Waifu System for Unicornia - Logic for waifu gifts and management
"""

import discord
from typing import List, Dict, Any, Tuple, Optional
from redbot.core import commands
from ..database import DatabaseManager

class WaifuSystem:
    """Handles waifu gifting and management logic"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
        
        # Default Nadeko gifts
        self.gifts = [
            {"name": "Potato", "emoji": "🥔", "price": 50, "negative": True},
            {"name": "Cookie", "emoji": "🍪", "price": 50, "negative": False},
            {"name": "Lollipop", "emoji": "🍭", "price": 150, "negative": False},
            {"name": "Rose", "emoji": "🌹", "price": 250, "negative": False},
            {"name": "Beer", "emoji": "🍺", "price": 300, "negative": False},
            {"name": "LoveLetter", "emoji": "💌", "price": 500, "negative": False},
            {"name": "Chocolate", "emoji": "🍫", "price": 1000, "negative": False},
            {"name": "Cake", "emoji": "🍰", "price": 3500, "negative": False},
            {"name": "Cat", "emoji": "🐱", "price": 5001, "negative": False},
            {"name": "Dog", "emoji": "🐶", "price": 5000, "negative": False},
            {"name": "Panda", "emoji": "🐼", "price": 5500, "negative": False},
            {"name": "Lipstick", "emoji": "💄", "price": 6000, "negative": False},
            {"name": "Purse", "emoji": "👛", "price": 7500, "negative": False},
            {"name": "Dress", "emoji": "👗", "price": 12500, "negative": False},
            {"name": "Whip", "emoji": "🧨", "price": 20000, "negative": False}, 
            {"name": "Ring", "emoji": "💍", "price": 25000, "negative": False},
            {"name": "Key", "emoji": "🗝️", "price": 30000, "negative": False},
            {"name": "Cage", "emoji": "🕸️", "price": 50000, "negative": False},
            {"name": "Buttplug", "emoji": "🔌", "price": 60000, "negative": False},
            {"name": "CherryKeeper", "emoji": "🍒", "price": 75000, "negative": False},
            {"name": "Crown", "emoji": "👑", "price": 100000, "negative": False},
            {"name": "Moon", "emoji": "🌕", "price": 150000, "negative": False},
        ]
        # Map for easier lookup
        self.gifts_map = {g["name"].lower(): g for g in self.gifts}

    def get_gifts(self) -> List[Dict[str, Any]]:
        """Get list of available gifts"""
        return self.gifts

    async def gift_waifu(self, giver: discord.Member, target: discord.Member, gift_name: str) -> Tuple[bool, str]:
        """Process gifting a waifu"""
        gift = self.gifts_map.get(gift_name.lower())
        if not gift:
            return False, "Gift not found. Use `[p]gifts` to see available items."

        # Check balance
        giver_balance = await self.db.economy.get_user_currency(giver.id)
        if giver_balance < gift["price"]:
            return False, f"Not enough currency. You need {gift['price']}."

        # Get waifu current price
        current_price = await self.db.waifu.get_waifu_price(target.id)
        
        # Calculate effect (90% of price)
        effect = int(gift["price"] * 0.9)
        
        # Calculate new price
        if gift["negative"]:
            # Ensure price doesn't drop below 1
            new_price = max(1, current_price - effect)
            effect_desc = f"decreased by {effect}"
        else:
            new_price = current_price + effect
            effect_desc = f"increased by {effect}"

        # Transaction
        # 1. Remove currency from giver
        await self.db.economy.remove_currency(giver.id, gift["price"], "waifu_gift", f"Gift {gift['name']} to {target.id}")
        
        # 2. Update waifu price
        await self.db.waifu.update_waifu_price(target.id, new_price)
        
        # 3. Add item to waifu inventory/history
        await self.db.waifu.add_waifu_item(target.id, gift["name"], gift["emoji"])
        
        return True, f"Gifted {gift['emoji']} **{gift['name']}** to **{target.display_name}**. Their price {effect_desc} to {new_price}."

    async def transfer_waifu(self, user: discord.Member, waifu_id: int, new_owner: discord.Member) -> Tuple[bool, str]:
        """Transfer waifu ownership"""
        # Check if user owns the waifu
        waifu = await self.db.waifu.get_waifu_info(waifu_id)
        if not waifu or waifu[1] != user.id: # waifu[1] is claimer_id
            return False, "You don't own this waifu."
            
        current_price = waifu[2]
        affinity_id = waifu[3]
        
        # Calculate fee
        # 10% fee normally, 60% if affinity
        fee_percent = 0.60 if affinity_id == user.id else 0.10
        fee = int(current_price * fee_percent)
        
        # Check balance
        user_balance = await self.db.economy.get_user_currency(user.id)
        if user_balance < fee:
            return False, f"Insufficient currency. Transfer fee is {fee} ({(fee_percent*100):.0f}% of value)."
            
        # Deduct fee
        await self.db.economy.remove_currency(user.id, fee, "waifu_transfer", f"Transfer waifu {waifu_id} to {new_owner.id}")
        
        # New price
        new_price = max(1, current_price - fee) # Transferred waifu's price will be reduced by the fee amount.
        
        # Perform transfer
        await self.db.waifu.transfer_waifu(waifu_id, new_owner.id, new_price)
        
        return True, f"Successfully transferred waifu to {new_owner.display_name}. Fee paid: {fee}. New price: {new_price}."

    async def reset_waifu(self, waifu_id: int) -> Tuple[bool, str]:
        """Admin reset waifu"""
        await self.db.waifu.admin_reset_waifu(waifu_id)
        return True, "Waifu has been reset (unclaimed and price set to 50)."