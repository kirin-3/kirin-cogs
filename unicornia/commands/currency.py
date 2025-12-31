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
            result = await self.currency_generation.pick_plant(ctx.author.id, ctx.channel.id)
            if result:
                amount, message_id = result
                currency_symbol = await self.config.currency_symbol()
                # Auto-delete confirmation after 30 seconds
                await ctx.reply(f"You picked up {amount}{currency_symbol}!", mention_author=False, delete_after=30)
                
                # Delete user command message after 30 seconds
                try:
                    await ctx.message.delete(delay=30)
                except Exception:
                    pass

                # Delete original message if ID exists
                if message_id:
                    try:
                        msg = await ctx.channel.fetch_message(message_id)
                        await msg.delete()
                    except (discord.NotFound, discord.Forbidden):
                        pass # Already deleted or no permissions
                    except Exception:
                        pass # Ignore other errors
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
