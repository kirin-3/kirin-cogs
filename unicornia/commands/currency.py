import discord
from redbot.core import commands, checks
from typing import Optional
from ..utils import systems_ready

class CurrencyCommands:
    # Currency generation commands
    @commands.group(name="currency")
    async def currency_group(self, ctx):
        """Currency generation and management commands"""
        pass
    
    @currency_group.command(name="pick")
    @systems_ready
    async def currency_pick(self, ctx, password: str):
        """Pick up a currency plant with the given password"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        try:
            success = await self.currency_generation.pick_plant(ctx.author.id, ctx.guild.id, password)
            if success:
                await ctx.send("✅ You picked up the currency plant!")
            else:
                await ctx.send("❌ No currency plant found with that password.")
                
        except Exception as e:
            await ctx.send(f"❌ Error picking currency plant: {e}")
