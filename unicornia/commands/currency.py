import discord
from redbot.core import commands, checks
from typing import Optional

class CurrencyCommands:
    # Currency generation commands
    @commands.group(name="currency")
    async def currency_group(self, ctx):
        """
        Currency generation and management.

        **Syntax**
        `[p]currency <subcommand>`
        """
        pass
    
    @commands.command(name="pick")
    async def pick_cmd(self, ctx):
        """
        Pick up generated currency.

        When currency spawns in chat, use this to claim it.

        **Syntax**
        `[p]pick`
        """
        if not await self.config.economy_enabled():
            await ctx.send("<a:zz_NoTick:729318761655435355> Economy system is disabled.")
            return
        
        try:
            result = await self.currency_generation.pick_plant(ctx.author.id, ctx.channel.id)
            if result:
                amount, message_ids, is_net_loss = result
                currency_symbol = await self.config.currency_symbol()
                
                if is_net_loss:
                    await ctx.reply(f"Wait... it was a fake! You lost {amount}{currency_symbol}!", mention_author=False, delete_after=30)
                else:
                    # Auto-delete confirmation after 30 seconds
                    await ctx.reply(f"You picked up {amount}{currency_symbol}!", mention_author=False, delete_after=30)
                
                # Delete user command message after 30 seconds
                try:
                    await ctx.message.delete(delay=30)
                except Exception:
                    pass

                # Delete original messages if IDs exist
                if message_ids:
                    for mid in message_ids:
                        try:
                            msg = await ctx.channel.fetch_message(mid)
                            await msg.delete()
                        except (discord.NotFound, discord.Forbidden):
                            pass # Already deleted or no permissions
                        except Exception:
                            pass # Ignore other errors
            else:
                await ctx.send("<a:zz_NoTick:729318761655435355> No currency to pick up here.", delete_after=15)
                
        except Exception as e:
            await ctx.send(f"<a:zz_NoTick:729318761655435355> Error picking currency: {e}")
            
    # Keep the old command as an alias or redirect if needed, or remove it.
    # For now, let's redirect it to the new one if they provide a password (ignore it)
    @currency_group.command(name="pick")
    async def currency_pick(self, ctx, password: str = None):
        """
        Pick up currency.

        Alias for `[p]pick`.

        **Syntax**
        `[p]currency pick`
        """
        await self.pick_cmd(ctx)
