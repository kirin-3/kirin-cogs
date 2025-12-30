"""
Nitro Shop Commands for Unicornia
"""

import discord
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_number, box

from ..views import NitroShopView

class NitroCommands:
    """Commands for the Nitro Shop system"""
    
    @commands.command(name="nitroshop")
    @commands.guild_only()
    async def nitroshop(self, ctx):
        """Open the Nitro Shop to purchase Discord Nitro subscriptions."""
        if not self.nitro_system:
            return await ctx.send("The Nitro Shop system is currently unavailable.")
            
        view = NitroShopView(ctx, self.nitro_system)
        # Initialize async components
        await view.init()
        
        embed = await view.get_embed()
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(name="nitrostock")
    @commands.is_owner()
    async def nitrostock(self, ctx, type: str, amount: int):
        """
        Set the stock for Nitro items.
        
        <type>: "boost" or "basic"
        <amount>: The exact amount of stock available
        """
        type = type.lower()
        if type not in ["boost", "basic"]:
            return await ctx.send("Invalid type. Use `boost` or `basic`.")
        
        if amount < 0:
            return await ctx.send("Stock cannot be negative.")
            
        new_amount = await self.nitro_system.set_stock(type, amount)
        
        await ctx.send(f"✅ Stock updated. New **Nitro {type.capitalize()}** stock: `{new_amount}`")

    @commands.command(name="nitroprice")
    @commands.is_owner()
    async def nitroprice(self, ctx, type: str, price: int):
        """
        Set the price for Nitro items.
        
        <type>: "boost" or "basic"
        <price>: New price in Slut points
        """
        type = type.lower()
        if type not in ["boost", "basic"]:
            return await ctx.send("Invalid type. Use `boost` or `basic`.")
            
        if price < 0:
            return await ctx.send("Price cannot be negative.")
            
        await self.nitro_system.set_price(type, price)
        
        await ctx.send(f"✅ Price updated. **Nitro {type.capitalize()}** now costs `{humanize_number(price)}` Slut points.")