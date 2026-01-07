"""
Nitro Shop Commands for Unicornia
"""

import discord
from redbot.core import commands, app_commands
from redbot.core.utils.chat_formatting import humanize_number, box

from ..views import NitroShopView

class NitroCommands:
    """Commands for the Nitro Shop system"""
    
    @commands.hybrid_command(name="nitroshop")
    @commands.guild_only()
    async def nitroshop(self, ctx):
        """
        Open the Nitro Shop.

        Exchange currency for Discord Nitro.

        **Syntax**
        `[p]nitroshop`
        """
        if not self.nitro_system:
            return await ctx.reply("The Nitro Shop system is currently unavailable.", mention_author=False)
            
        view = NitroShopView(ctx, self.nitro_system)
        # Initialize async components
        await view.init()
        
        embed = await view.get_embed()
        view.message = await ctx.reply(embed=embed, view=view, mention_author=False)

    @commands.command(name="nitrostock")
    @commands.is_owner()
    async def nitrostock(self, ctx, type: str, amount: int):
        """
        Set Nitro stock.

        **Owner only.**

        **Syntax**
        `[p]nitrostock <type> <amount>`

        **Types**
        `boost`, `basic`
        """
        type = type.lower()
        if type not in ["boost", "basic"]:
            return await ctx.send("Invalid type. Use `boost` or `basic`.")
        
        if amount < 0:
            return await ctx.send("Stock cannot be negative.")
            
        new_amount = await self.nitro_system.set_stock(type, amount)
        
        await ctx.send(f"<a:zz_YesTick:729318762356015124> Stock updated. New **Nitro {type.capitalize()}** stock: `{new_amount}`")

    @commands.command(name="nitroprice")
    @commands.is_owner()
    async def nitroprice(self, ctx, type: str, price: int):
        """
        Set Nitro price.

        **Owner only.**

        **Syntax**
        `[p]nitroprice <type> <price>`
        """
        type = type.lower()
        if type not in ["boost", "basic"]:
            return await ctx.send("Invalid type. Use `boost` or `basic`.")
            
        if price < 0:
            return await ctx.send("Price cannot be negative.")
            
        await self.nitro_system.set_price(type, price)
        
        await ctx.send(f"<a:zz_YesTick:729318762356015124> Price updated. **Nitro {type.capitalize()}** now costs `{humanize_number(price)}` Slut points.")
