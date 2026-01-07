import discord
from redbot.core import commands, checks, app_commands
from typing import Optional, Union
from ..views import RockPaperScissorsView, CoinFlipView

class GamblingCommands:
    async def _resolve_bet(self, ctx, amount: Union[int, str]) -> Optional[int]:
        """Resolve bet amount from int or 'all'"""
        if isinstance(amount, str):
            if amount.lower() == "all":
                balance = await self.db.economy.get_user_currency(ctx.author.id)
                if balance <= 0:
                    await ctx.reply("<a:zz_NoTick:729318761655435355> You don't have any currency to bet.", mention_author=False)
                    return None
                return balance
            else:
                try:
                    amount = int(amount)
                except ValueError:
                    await ctx.reply("<a:zz_NoTick:729318761655435355> Invalid bet amount.", mention_author=False)
                    return None
        
        if amount <= 0:
            await ctx.reply("<a:zz_NoTick:729318761655435355> Amount must be positive.", mention_author=False)
            return None
            
        return amount

    # Gambling commands
    @commands.hybrid_group(name="gambling", aliases=["gamble"])
    async def gambling_group(self, ctx):
        """
        Play gambling games to win currency.

        **Syntax**
        `[p]gambling <game> <amount>`
        """
        pass
    
    @gambling_group.command(name="betroll", aliases=["roll"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet")
    async def gambling_betroll(self, ctx, amount: str):
        """
        Roll a 100-sided die.
        
        Roll 66 or higher to win.
        Payout scales with the roll.

        **Syntax**
        `[p]gambling betroll <amount>`

        **Examples**
        `[p]gambling betroll 100`
        """
        if not await self.config.gambling_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Gambling is disabled.", mention_author=False)
            return
        
        if not await self.config.economy_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Economy system is disabled.", mention_author=False)
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
        
        try:
            success, result = await self.gambling_system.betroll(ctx.author.id, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.", mention_author=False)
                else:
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error: {result.get('error', 'Unknown error')}", mention_author=False)
                return
            
            currency_symbol = await self.config.currency_symbol()
            if result["won"]:
                await ctx.reply(f"🎲 You rolled **{result['roll']}** (needed {result['threshold']}+) and won {currency_symbol}{result['win_amount']:,}!", mention_author=False)
            else:
                await ctx.reply(f"🎲 You rolled **{result['roll']}** (needed {result['threshold']}+) and lost {currency_symbol}{result['loss_amount']:,}. Better luck next time!", mention_author=False)
                
        except Exception as e:
            await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error in gambling: {e}", mention_author=False)
    
    @gambling_group.command(name="rps", aliases=["rockpaperscissors"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(choice="rock, paper, or scissors", amount="Amount to bet")
    async def gambling_rps(self, ctx, choice: Optional[str] = None, amount: str = "0"):
        """
        Play Rock, Paper, Scissors against the bot.

        **Syntax**
        `[p]gambling rps [choice] [amount]`
        `[p]gambling rps <amount>` (Interactive)

        **Examples**
        `[p]gambling rps rock 100`
        `[p]gambling rps 100`
        """
        if not await self.config.gambling_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Gambling is disabled.", mention_author=False)
            return
        
        if not await self.config.economy_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Economy system is disabled.", mention_author=False)
            return

        # Handle flexible arguments: [p]rps 100 -> choice="100", amount=0
        if choice and (choice.isdigit() or choice.lower() == "all") and (amount == "0" or amount == 0):
            amount = choice
            choice = None
            
        if choice is None:
            view = RockPaperScissorsView(ctx.author)
            view.message = await ctx.reply("Choose your weapon!", view=view, mention_author=False)
            await view.wait()
            
            if view.choice is None:
                await ctx.reply("<a:zz_NoTick:729318761655435355> Timed out.", mention_author=False)
                return
            choice = view.choice
        
        if amount != "0" and amount != 0:
            amount = await self._resolve_bet(ctx, amount)
            if amount is None:
                return
        
        try:
            success, result = await self.gambling_system.rock_paper_scissors(ctx.author.id, choice, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.", mention_author=False)
                elif result.get("error") == "invalid_choice":
                    await ctx.reply("<a:zz_NoTick:729318761655435355> Please choose: rock, paper, or scissors", mention_author=False)
                else:
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error: {result.get('error', 'Unknown error')}", mention_author=False)
                return
            
            currency_symbol = await self.config.currency_symbol()
            if amount > 0:
                if result["result"] == "win":
                    await ctx.reply(f"{result['user_choice']} vs {result['bot_choice']} - You won {currency_symbol}{result['win_amount']:,}!", mention_author=False)
                elif result["result"] == "lose":
                    await ctx.reply(f"{result['user_choice']} vs {result['bot_choice']} - You lost {currency_symbol}{result['loss_amount']:,}!", mention_author=False)
                else:
                    await ctx.reply(f"{result['user_choice']} vs {result['bot_choice']} - It's a draw! No Slut points lost.", mention_author=False)
            else:
                if result["result"] == "win":
                    await ctx.reply(f"{result['user_choice']} vs {result['bot_choice']} - You win!", mention_author=False)
                elif result["result"] == "lose":
                    await ctx.reply(f"{result['user_choice']} vs {result['bot_choice']} - You lose!", mention_author=False)
                else:
                    await ctx.reply(f"{result['user_choice']} vs {result['bot_choice']} - It's a draw!", mention_author=False)
                
        except Exception as e:
            await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error in RPS: {e}", mention_author=False)
    
    @gambling_group.command(name="slots")
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet")
    async def gambling_slots(self, ctx, amount: str):
        """
        Play the slot machine.
        
        Match symbols to win big multipliers.

        **Syntax**
        `[p]gambling slots <amount>`

        **Examples**
        `[p]gambling slots 500`
        """
        if not await self.config.gambling_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Gambling is disabled.", mention_author=False)
            return
        
        if not await self.config.economy_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Economy system is disabled.", mention_author=False)
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
        
        try:
            success, result = await self.gambling_system.slots(ctx.author.id, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.", mention_author=False)
                else:
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error: {result.get('error', 'Unknown error')}", mention_author=False)
                return
            
            currency_symbol = await self.config.currency_symbol()
            rolls_str = "".join(map(str, result['rolls']))
            
            if result['won_amount'] > 0:
                await ctx.reply(f"🎰 **{rolls_str}** - {result['win_type'].replace('_', ' ').title()}! You won {currency_symbol}{result['won_amount']:,}!", mention_author=False)
            else:
                await ctx.reply(f"🎰 **{rolls_str}** - Better luck next time! You lost {currency_symbol}{amount:,}.", mention_author=False)
                
        except Exception as e:
            await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error in slots: {e}", mention_author=False)

    @gambling_group.command(name="blackjack", aliases=["21"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet")
    async def gambling_blackjack(self, ctx, amount: str):
        """
        Play a game of Blackjack (21).

        **Syntax**
        `[p]gambling blackjack <amount>`
        """
        if not await self.config.gambling_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Gambling is disabled.", mention_author=False)
            return
        
        if not await self.config.economy_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Economy system is disabled.", mention_author=False)
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
            
        try:
            await self.gambling_system.play_blackjack(ctx, amount)
        except Exception as e:
            await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error in blackjack: {e}", mention_author=False)

    @gambling_group.command(name="betflip", aliases=["bf"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet", guess="heads or tails")
    async def gambling_betflip(self, ctx, amount: str, guess: Optional[str] = None):
        """
        Bet on a coin flip.

        Guess Heads or Tails to double your bet.

        **Syntax**
        `[p]gambling betflip <amount> [guess]`

        **Examples**
        `[p]gambling betflip 100 heads`
        `[p]gambling betflip 100` (Interactive)
        """
        if not await self.config.gambling_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Gambling is disabled.", mention_author=False)
            return
        
        if not await self.config.economy_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Economy system is disabled.", mention_author=False)
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return

        if guess is None:
            view = CoinFlipView(ctx.author)
            view.message = await ctx.reply(f"You are betting {amount}. Choose Heads or Tails:", view=view, mention_author=False)
            await view.wait()
            
            if view.choice is None:
                await ctx.reply("<a:zz_NoTick:729318761655435355> Timed out.", mention_author=False)
                return
            guess = view.choice
            
        try:
            success, result = await self.gambling_system.bet_flip(ctx.author.id, amount, guess)
            
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.", mention_author=False)
                elif result.get("error") == "invalid_guess":
                    await ctx.reply("<a:zz_NoTick:729318761655435355> Invalid guess. Please choose 'heads' or 'tails'.", mention_author=False)
                else:
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error: {result.get('error', 'Unknown error')}", mention_author=False)
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
                
            await ctx.reply(embed=embed, mention_author=False)
            
        except Exception as e:
            await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error in betflip: {e}", mention_author=False)
    
    @gambling_group.command(name="luckyladder", aliases=["ladder"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet")
    async def gambling_lucky_ladder(self, ctx, amount: str):
        """
        Climb the lucky ladder.
        
        The higher you climb, the higher the multiplier.

        **Syntax**
        `[p]gambling luckyladder <amount>`
        """
        if not await self.config.gambling_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Gambling is disabled.", mention_author=False)
            return
        
        if not await self.config.economy_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Economy system is disabled.", mention_author=False)
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
        
        try:
            success, result = await self.gambling_system.lucky_ladder(ctx.author.id, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> You don't have enough {currency_symbol} Slut points. You have {currency_symbol}{result['balance']:,}.", mention_author=False)
                else:
                    await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error: {result.get('error', 'Unknown error')}", mention_author=False)
                return
            
            currency_symbol = await self.config.currency_symbol()
            if result['won_amount'] > amount:
                await ctx.reply(f"🪜 Rung {result['rung']} - {result['multiplier']}x multiplier! You won {currency_symbol}{result['won_amount']:,}!", mention_author=False)
            else:
                await ctx.reply(f"🪜 Rung {result['rung']} - {result['multiplier']}x multiplier. You lost {currency_symbol}{amount - result['won_amount']:,}.", mention_author=False)
                
        except Exception as e:
            await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error in lucky ladder: {e}", mention_author=False)

    @gambling_group.command(name="mines", aliases=["minesweeper"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet", mines="Number of mines (1-19)")
    async def gambling_mines(self, ctx, amount: Optional[str] = None, mines: int = 3):
        """
        Play Minesweeper for currency.

        Reveal safe squares to increase multiplier. Cash out anytime.

        **Syntax**
        `[p]gambling mines <amount> [mines]`
        `[p]gambling mines` (Tutorial)

        **Examples**
        `[p]gambling mines 100 3`
        """
        if amount is None:
            embed = discord.Embed(
                title="💣 Mines - How to Play",
                description="Mines is a high-stakes gambling game where you reveal safe spots on a grid to increase your multiplier.",
                color=discord.Color.red()
            )
            embed.add_field(
                name="How it works",
                value=(
                    "1. Bet an amount of currency and choose the number of mines (1-19).\n"
                    "2. Click the buttons 🟦 to reveal what's underneath.\n"
                    "3. Find safe spots 💎 to increase your multiplier.\n"
                    "4. Hit a mine 💣 and you lose your bet.\n"
                    "5. Click **Cash Out** at any time to take your winnings!"
                ),
                inline=False
            )
            embed.add_field(
                name="Usage",
                value=f"`{ctx.clean_prefix}mines <amount> [mines]`\nExample: `{ctx.clean_prefix}mines 100 3` (Bet 100, 3 mines)",
                inline=False
            )
            embed.set_footer(text=f"Default mines: 3. Max mines: 19.")
            await ctx.send(embed=embed)
            return

        if not await self.config.gambling_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Gambling is disabled.", mention_author=False)
            return
        
        if not await self.config.economy_enabled():
            await ctx.reply("<a:zz_NoTick:729318761655435355> Economy system is disabled.", mention_author=False)
            return
        
        amount = await self._resolve_bet(ctx, amount)
        if amount is None:
            return
            
        try:
            await self.gambling_system.play_mines(ctx, amount, mines)
        except Exception as e:
            await ctx.reply(f"<a:zz_NoTick:729318761655435355> Error in Mines: {e}", mention_author=False)

    # Top-level aliases for gambling commands
    @commands.hybrid_command(name="betroll", aliases=["roll"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet")
    async def top_betroll(self, ctx, amount: str):
        """
        Roll a 100-sided die.

        Alias for `[p]gambling betroll`.

        **Syntax**
        `[p]betroll <amount>`
        """
        await self.gambling_betroll(ctx, amount)

    @commands.hybrid_command(name="rps", aliases=["rockpaperscissors"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(choice="rock, paper, or scissors", amount="Amount to bet")
    async def top_rps(self, ctx, choice: Optional[str] = None, amount: str = "0"):
        """
        Play Rock, Paper, Scissors.

        Alias for `[p]gambling rps`.

        **Syntax**
        `[p]rps [choice] [amount]`
        """
        await self.gambling_rps(ctx, choice, amount)

    @commands.hybrid_command(name="slots")
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet")
    async def top_slots(self, ctx, amount: str):
        """
        Play the slot machine.

        Alias for `[p]gambling slots`.

        **Syntax**
        `[p]slots <amount>`
        """
        await self.gambling_slots(ctx, amount)

    @commands.command(name="blackjack", aliases=["21"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    async def top_blackjack(self, ctx, amount: str):
        """
        Play Blackjack.

        Alias for `[p]gambling blackjack`.

        **Syntax**
        `[p]blackjack <amount>`
        """
        await self.gambling_blackjack(ctx, amount)

    @commands.hybrid_command(name="betflip", aliases=["bf"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet", guess="heads or tails")
    async def top_betflip(self, ctx, amount: str, guess: Optional[str] = None):
        """
        Bet on a coin flip.

        Alias for `[p]gambling betflip`.

        **Syntax**
        `[p]betflip <amount> [guess]`
        """
        await self.gambling_betflip(ctx, amount, guess)

    @commands.hybrid_command(name="luckyladder", aliases=["ladder"])
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet")
    async def top_luckyladder(self, ctx, amount: str):
        """
        Climb the lucky ladder.

        Alias for `[p]gambling luckyladder`.

        **Syntax**
        `[p]luckyladder <amount>`
        """
        await self.gambling_lucky_ladder(ctx, amount)

    @commands.hybrid_command(name="mines")
    @commands.cooldown(1, 1, commands.BucketType.user)
    @app_commands.describe(amount="Amount to bet", mines="Number of mines (1-19)")
    async def top_mines(self, ctx, amount: Optional[str] = None, mines: int = 3):
        """
        Play Mines.

        Alias for `[p]gambling mines`.

        **Syntax**
        `[p]mines <amount> [mines]`
        """
        await self.gambling_mines(ctx, amount, mines)
