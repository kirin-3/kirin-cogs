import discord
from redbot.core import commands, checks
from typing import Optional, Union

class GamblingCommands:
    async def _resolve_bet(self, ctx, amount: Union[int, str]) -> Optional[int]:
        """Resolve bet amount from int or 'all'"""
        if isinstance(amount, str):
            if amount.lower() == "all":
                balance = await self.db.economy.get_user_currency(ctx.author.id)
                if balance <= 0:
                    await ctx.send("❌ You don't have any currency to bet.")
                    return None
                return balance
            else:
                try:
                    amount = int(amount)
                except ValueError:
                    await ctx.send("❌ Invalid bet amount.")
                    return None
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return None
            
        return amount

    # Gambling commands
    @commands.group(name="gambling", aliases=["gamble"])
    async def gambling_group(self, ctx):
        """Gambling commands"""
        pass
    
    @gambling_group.command(name="betroll", aliases=["roll"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def gambling_betroll(self, ctx, amount: Union[int, str]):
        """Bet on a dice roll (1-100)"""
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
        
        try:
            success, result = await self.gambling_system.betroll(ctx.author.id, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.send(f"❌ You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.")
                else:
                    await ctx.send(f"❌ Error: {result.get('error', 'Unknown error')}")
                return
            
            currency_symbol = await self.config.currency_symbol()
            if result["won"]:
                await ctx.send(f"🎲 You rolled **{result['roll']}** (needed {result['threshold']}+) and won {currency_symbol}{result['win_amount']:,}!")
            else:
                await ctx.send(f"🎲 You rolled **{result['roll']}** (needed {result['threshold']}+) and lost {currency_symbol}{result['loss_amount']:,}. Better luck next time!")
                
        except Exception as e:
            await ctx.send(f"❌ Error in gambling: {e}")
    
    @gambling_group.command(name="rps", aliases=["rockpaperscissors"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def gambling_rps(self, ctx, choice: str, amount: Union[int, str] = 0):
        """Play rock paper scissors"""
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount != 0:
            amount = await self._resolve_bet(ctx, amount)
            if amount is None:
                return
        
        try:
            success, result = await self.gambling_system.rock_paper_scissors(ctx.author.id, choice, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.send(f"❌ You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.")
                elif result.get("error") == "invalid_choice":
                    await ctx.send("❌ Please choose: rock, paper, or scissors")
                else:
                    await ctx.send(f"❌ Error: {result.get('error', 'Unknown error')}")
                return
            
            currency_symbol = await self.config.currency_symbol()
            if amount > 0:
                if result["result"] == "win":
                    await ctx.send(f"{result['user_choice']} vs {result['bot_choice']} - You won {currency_symbol}{result['win_amount']:,}!")
                elif result["result"] == "lose":
                    await ctx.send(f"{result['user_choice']} vs {result['bot_choice']} - You lost {currency_symbol}{result['loss_amount']:,}!")
                else:
                    await ctx.send(f"{result['user_choice']} vs {result['bot_choice']} - It's a draw! No Slut points lost.")
            else:
                if result["result"] == "win":
                    await ctx.send(f"{result['user_choice']} vs {result['bot_choice']} - You win!")
                elif result["result"] == "lose":
                    await ctx.send(f"{result['user_choice']} vs {result['bot_choice']} - You lose!")
                else:
                    await ctx.send(f"{result['user_choice']} vs {result['bot_choice']} - It's a draw!")
                
        except Exception as e:
            await ctx.send(f"❌ Error in RPS: {e}")
    
    @gambling_group.command(name="slots")
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def gambling_slots(self, ctx, amount: Union[int, str]):
        """Play slots"""
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
        
        try:
            success, result = await self.gambling_system.slots(ctx.author.id, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.send(f"❌ You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.")
                else:
                    await ctx.send(f"❌ Error: {result.get('error', 'Unknown error')}")
                return
            
            currency_symbol = await self.config.currency_symbol()
            rolls_str = "".join(map(str, result['rolls']))
            
            if result['won_amount'] > 0:
                await ctx.send(f"🎰 **{rolls_str}** - {result['win_type'].replace('_', ' ').title()}! You won {currency_symbol}{result['won_amount']:,}!")
            else:
                await ctx.send(f"🎰 **{rolls_str}** - Better luck next time! You lost {currency_symbol}{amount:,}.")
                
        except Exception as e:
            await ctx.send(f"❌ Error in slots: {e}")

    @gambling_group.command(name="blackjack", aliases=["bj", "21"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def gambling_blackjack(self, ctx, amount: Union[int, str]):
        """Play blackjack"""
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
            
        try:
            # Note: play_blackjack handles interaction and responses internally
            await self.gambling_system.play_blackjack(ctx, amount)
        except Exception as e:
            await ctx.send(f"❌ Error in blackjack: {e}")

    @gambling_group.command(name="betflip", aliases=["bf"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def gambling_betflip(self, ctx, amount: Union[int, str], guess: str):
        """Bet on a coin flip (Heads or Tails)
        
        Usage: [p]gambling betflip 100 heads
        """
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
            
        try:
            success, result = await self.gambling_system.bet_flip(ctx.author.id, amount, guess)
            
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.send(f"❌ You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.")
                elif result.get("error") == "invalid_guess":
                    await ctx.send("❌ Invalid guess. Please choose 'heads' or 'tails'.")
                else:
                    await ctx.send(f"❌ Error: {result.get('error', 'Unknown error')}")
                return
            
            currency_symbol = await self.config.currency_symbol()
            
            # Create embed
            embed = discord.Embed(title="🪙 Coin Flip", color=discord.Color.gold())
            
            # Simple visualization with emojis
            if result["result"] == "Heads":
                embed.description = "The coin landed on **Heads**!"
                # Could add image url here if configured
            else:
                embed.description = "The coin landed on **Tails**!"
                
            if result["won"]:
                embed.color = discord.Color.green()
                embed.add_field(name="Result", value=f"You guessed {result['guess']} and won {currency_symbol}{result['win_amount']:,}!", inline=False)
            else:
                embed.color = discord.Color.red()
                embed.add_field(name="Result", value=f"You guessed {result['guess']} and lost {currency_symbol}{result['loss_amount']:,}.", inline=False)
                
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error in betflip: {e}")
    
    @gambling_group.command(name="luckyladder", aliases=["ladder"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def gambling_lucky_ladder(self, ctx, amount: Union[int, str]):
        """Play lucky ladder"""
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
        
        try:
            success, result = await self.gambling_system.lucky_ladder(ctx.author.id, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.send(f"❌ You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.")
                else:
                    await ctx.send(f"❌ Error: {result.get('error', 'Unknown error')}")
                return
            
            currency_symbol = await self.config.currency_symbol()
            if result['won_amount'] > amount:
                await ctx.send(f"🪜 Rung {result['rung']} - {result['multiplier']}x multiplier! You won {currency_symbol}{result['won_amount']:,}!")
            else:
                await ctx.send(f"🪜 Rung {result['rung']} - {result['multiplier']}x multiplier. You lost {currency_symbol}{amount - result['won_amount']:,}.")
                
        except Exception as e:
            await ctx.send(f"❌ Error in lucky ladder: {e}")

    # Top-level aliases for gambling commands
    @commands.command(name="betroll", aliases=["roll"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def top_betroll(self, ctx, amount: Union[int, str]):
        """Bet on a dice roll (1-100)"""
        await self.gambling_betroll(ctx, amount)

    @commands.command(name="rps", aliases=["rockpaperscissors"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def top_rps(self, ctx, choice: str, amount: Union[int, str] = 0):
        """Play rock paper scissors"""
        await self.gambling_rps(ctx, choice, amount)

    @commands.command(name="slots")
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def top_slots(self, ctx, amount: Union[int, str]):
        """Play slots"""
        await self.gambling_slots(ctx, amount)

    @commands.command(name="blackjack", aliases=["bj", "21"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def top_blackjack(self, ctx, amount: Union[int, str]):
        """Play blackjack"""
        await self.gambling_blackjack(ctx, amount)

    @commands.command(name="betflip", aliases=["bf"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def top_betflip(self, ctx, amount: Union[int, str], guess: str):
        """Bet on a coin flip (Heads or Tails)"""
        await self.gambling_betflip(ctx, amount, guess)

    @commands.command(name="luckyladder", aliases=["ladder"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def top_luckyladder(self, ctx, amount: Union[int, str]):
        """Play lucky ladder"""
        await self.gambling_lucky_ladder(ctx, amount)
