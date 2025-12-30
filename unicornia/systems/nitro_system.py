"""
Nitro Shop System for Unicornia
Handles stock management, purchases, and notifications for Discord Nitro items.
"""

import discord
import logging
from typing import Literal, Tuple, Optional
from redbot.core import Config
from redbot.core.utils.chat_formatting import humanize_number

log = logging.getLogger("red.unicornia.nitro")

class NitroSystem:
    def __init__(self, config: Config, bot, economy_system):
        self.config = config
        self.bot = bot
        self.economy_system = economy_system
        
        # Hardcoded channel and user IDs as per requirements
        self.ANNOUNCE_CHANNEL_ID = 695155004507422730
        self.ADMIN_NOTIFY_USER_ID = 140186220255903746
        
        # Define defaults if they don't exist in config yet
        # We'll use a specific group for nitro shop
        self.config.register_global(
            nitro_stock={
                "boost": 0,
                "basic": 0
            },
            nitro_prices={
                "boost": 250000,
                "basic": 150000
            }
        )

    async def get_stock(self, item_type: Literal["boost", "basic"]) -> int:
        """Get current stock for an item type"""
        stock = await self.config.nitro_stock()
        return stock.get(item_type, 0)

    async def get_price(self, item_type: Literal["boost", "basic"]) -> int:
        """Get current price for an item type"""
        prices = await self.config.nitro_prices()
        return prices.get(item_type, 0)

    async def set_price(self, item_type: Literal["boost", "basic"], price: int):
        """Set price for an item type"""
        async with self.config.nitro_prices() as prices:
            prices[item_type] = price

    async def add_stock(self, item_type: Literal["boost", "basic"], amount: int) -> int:
        """Add (or remove) stock and announce if adding"""
        async with self.config.nitro_stock() as stock:
            current = stock.get(item_type, 0)
            new_amount = current + amount
            # Ensure we don't go below 0
            if new_amount < 0:
                new_amount = 0
            stock[item_type] = new_amount
            
        # Only announce if we're adding positive stock
        if amount > 0:
            await self._announce_stock(item_type, amount)
            
        return new_amount

    async def purchase_nitro(self, ctx, item_type: Literal["boost", "basic"]) -> Tuple[bool, str]:
        """Process a nitro purchase transaction"""
        # 1. Check stock
        stock = await self.get_stock(item_type)
        if stock <= 0:
            return False, "This item is currently out of stock!"

        # 2. Check price and balance
        price = await self.get_price(item_type)
        wallet, bank = await self.economy_system.get_balance(ctx.author.id)
        
        if wallet < price:
            return False, f"You need {humanize_number(price)} to purchase this item. You only have {humanize_number(wallet)} in your wallet."

        # 3. Process transaction (Deduct money)
        success = await self.economy_system.take_currency(ctx.author.id, price, note=f"Nitro Shop: {item_type}")
        if not success:
            return False, "Transaction failed during currency deduction."

        # 4. Update stock (Decrement)
        async with self.config.nitro_stock() as s:
            # Double check stock to prevent race conditions (simple check)
            if s.get(item_type, 0) <= 0:
                # Refund if stock ran out suddenly
                await self.economy_system.award_currency(ctx.author.id, price, note=f"Nitro Shop Refund: {item_type}")
                return False, "This item just went out of stock!"
            
            s[item_type] -= 1

        # 5. Notify Admins
        await self._notify_admin(ctx, item_type)
        
        return True, "Purchase successful! An admin has been notified and will send your code shortly."

    async def _announce_stock(self, item_type: str, amount: int):
        """Announce new stock to the public channel"""
        channel = self.bot.get_channel(self.ANNOUNCE_CHANNEL_ID)
        if not channel:
            log.warning(f"Nitro Announce Channel {self.ANNOUNCE_CHANNEL_ID} not found.")
            return

        pretty_name = "Nitro Boost" if item_type == "boost" else "Nitro Basic"
        
        embed = discord.Embed(
            title="🎉 New Nitro Stock Available!",
            description=f"**{amount}x {pretty_name}** has just been restocked!",
            color=discord.Color.nitro_pink()
        )
        embed.add_field(name="How to buy?", value=f"Use the command `[p]nitroshop` to purchase.")
        
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.error(f"Missing permissions to send to Nitro Announce Channel {self.ANNOUNCE_CHANNEL_ID}")

    async def _notify_admin(self, ctx, item_type: str):
        """Notify bot owners and specific admin about the purchase"""
        pretty_name = "Nitro Boost" if item_type == "boost" else "Nitro Basic"
        
        embed = discord.Embed(
            title="🔔 New Nitro Purchase",
            color=discord.Color.green(),
            timestamp=ctx.message.created_at
        )
        embed.add_field(name="Buyer", value=f"{ctx.author.mention} (`{ctx.author.id}`)", inline=False)
        embed.add_field(name="Item", value=pretty_name, inline=True)
        embed.add_field(name="Price Paid", value=humanize_number(await self.get_price(item_type)), inline=True)
        embed.set_footer(text="Please send the code to the user.")

        # Notify Bot Owners
        owners = await self.bot.get_owners()
        for owner_id in owners:
            try:
                owner = await self.bot.get_or_fetch_user(owner_id)
                if owner:
                    await owner.send(embed=embed)
            except discord.HTTPException as e:
                log.error(f"Failed to DM owner {owner_id}: {e}")

        # Notify Specific Admin (if not already an owner to avoid double DMs, but usually safe to just send)
        # Requirement: "send a DM to user with the ID 140186220255903746"
        if self.ADMIN_NOTIFY_USER_ID not in owners:
            try:
                admin = await self.bot.get_or_fetch_user(self.ADMIN_NOTIFY_USER_ID)
                if admin:
                    await admin.send(embed=embed)
            except discord.HTTPException as e:
                log.error(f"Failed to DM admin {self.ADMIN_NOTIFY_USER_ID}: {e}")