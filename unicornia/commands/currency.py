import discord
from redbot.core import commands, checks
from typing import Optional

class CurrencyCommands:
    # Currency generation commands
    @commands.group(name="currency")
    async def currency_group(self, ctx):
        """Currency generation and management commands"""
        pass
    
    @commands.command(name="pick")
    async def pick_cmd(self, ctx):
        """Pick up generated currency"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        try:
            amount = await self.currency_generation.pick_plant(ctx.author.id, ctx.channel.id)
            if amount:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"✅ You picked up {amount}{currency_symbol}!")
            else:
                await ctx.send("❌ No currency to pick up here.")
                
        except Exception as e:
            await ctx.send(f"❌ Error picking currency: {e}")
            
    # Keep the old command as an alias or redirect if needed, or remove it.
    # For now, let's redirect it to the new one if they provide a password (ignore it)
    @currency_group.command(name="pick")
    async def currency_pick(self, ctx, password: str = None):
        """Pick up currency (alias for [p]pick)"""
        await self.pick_cmd(ctx)
