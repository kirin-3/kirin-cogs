import discord
from redbot.core import commands, checks, app_commands
from redbot.core.utils.views import SimpleMenu
from typing import Optional
from ..utils import validate_text_input
from ..views import LeaderboardView

class EconomyCommands:
    # Economy commands
    @commands.hybrid_command(name="baltop", aliases=["ballb"])
    async def baltop_shortcut(self, ctx):
        """Show the Slut points leaderboard"""
        await self.economy_leaderboard(ctx)

    @commands.hybrid_group(name="economy", aliases=["econ", "money"])
    async def economy_group(self, ctx):
        """Economy and currency commands"""
        pass
    
    @economy_group.command(name="balance", aliases=["bal", "wallet"])
    @app_commands.describe(member="The user to check balance for")
    async def economy_balance(self, ctx, member: discord.Member = None):
        """Check your or another user's Slut points balance"""
        await self._balance_logic(ctx, member)

    @commands.hybrid_command(name="balance", aliases=["bal", "$", "€", "£"])
    @app_commands.describe(member="The user to check balance for")
    async def global_balance(self, ctx, member: discord.Member = None):
        """Check your or another user's balance"""
        await self._balance_logic(ctx, member)

    @commands.hybrid_command(name="wallet")
    @app_commands.describe(member="The user to check wallet for")
    async def wallet_command(self, ctx, member: discord.Member = None):
        """Check your or another user's wallet (Alias for balance)"""
        await self._balance_logic(ctx, member)

    async def _balance_logic(self, ctx, member: discord.Member = None):
        """Shared logic for balance commands"""
        if not await self.config.economy_enabled():
            await ctx.reply("❌ Economy system is disabled.", mention_author=False)
            return
        
        member = member or ctx.author
        
        try:
            wallet_balance, bank_balance = await self.economy_system.get_balance(member.id)
            currency_symbol = await self.config.currency_symbol()
            
            embed = discord.Embed(
                title=f"{member.display_name}'s Balance",
                color=member.color or discord.Color.green()
            )
            embed.add_field(name=f"{currency_symbol} Currency", value=f"{currency_symbol}{wallet_balance:,}", inline=True)
            embed.add_field(name="🏦 Bank", value=f"{currency_symbol}{bank_balance:,}", inline=True)
            embed.add_field(name="💎 Total", value=f"{currency_symbol}{wallet_balance + bank_balance:,}", inline=True)
            
            await ctx.reply(embed=embed, mention_author=False)
            
        except Exception as e:
            await ctx.reply(f"❌ Error retrieving balance: {e}", mention_author=False)
    
    @economy_group.command(name="give")
    async def economy_give(self, ctx, amount: int, member: discord.Member, *, note: str = ""):
        """Give Slut points to another user"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        if member.bot:
            await ctx.send("❌ You can't give Slut points to bots.")
            return
        
        if member == ctx.author:
            await ctx.send("❌ You can't give Slut points to yourself.")
            return
            
        # Immediate length check to prevent DoS from massive input strings
        if len(note) > 200:
            await ctx.send("❌ Note is too long (max 200 chars).")
            return

        if not validate_text_input(note, max_length=200):
            await ctx.send("❌ Note is too long (max 200 chars).")
            return
        
        try:
            success = await self.economy_system.give_currency(ctx.author.id, member.id, amount, note)
            if success:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"✅ You gave {currency_symbol}{amount:,} to {member.mention}!")
            else:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"❌ You don't have enough {currency_symbol} Slut points.")
                
        except Exception as e:
            await ctx.send(f"❌ Error transferring Slut points: {e}")
    
    @economy_group.command(name="timely", aliases=["daily"])
    @commands.cooldown(1, 86400, commands.BucketType.user)  # 24 hours cooldown
    async def economy_timely(self, ctx):
        """Claim your daily Slut points reward"""
        await self._timely_logic(ctx)

    @commands.hybrid_command(name="timely", aliases=["daily"])
    @commands.cooldown(1, 86400, commands.BucketType.user)  # 24 hours cooldown
    async def global_timely(self, ctx):
        """Claim your daily reward"""
        await self._timely_logic(ctx)

    async def _timely_logic(self, ctx):
        """Shared logic for timely commands"""
        if not await self.config.economy_enabled():
            await ctx.reply("❌ Economy system is disabled.", mention_author=False)
            return
        
        try:
            success, amount, streak, breakdown = await self.economy_system.claim_timely(ctx.author)
            
            if success:
                currency_symbol = await self.config.currency_symbol()
                
                embed = discord.Embed(
                    title="💰 Daily Reward Claimed!",
                    description=f"You received **{currency_symbol}{amount:,}**!",
                    color=discord.Color.green()
                )
                
                details = []
                details.append(f"• Base Pay: {currency_symbol}{breakdown.get('base', 0):,}")
                
                # Streak
                streak_bonus = breakdown.get('streak', 0)
                details.append(f"• Streak: {streak} days (+{currency_symbol}{streak_bonus:,})")
                
                # Supporter
                supporter_amount = breakdown.get('supporter', 0)
                supporter_mark = "✅" if supporter_amount > 0 else "❌"
                details.append(f"• Supporter Bonus: {supporter_mark} {currency_symbol}{supporter_amount:,}")
                
                # Booster
                booster_amount = breakdown.get('booster', 0)
                booster_mark = "✅" if booster_amount > 0 else "❌"
                details.append(f"• Booster Bonus: {booster_mark} {currency_symbol}{booster_amount:,}")
                
                embed.add_field(name="Reward Breakdown", value="\n".join(details), inline=False)
                await ctx.reply(embed=embed, mention_author=False)
            else:
                cooldown_hours = await self.config.timely_cooldown()
                await ctx.reply(f"❌ You can claim your daily reward in {cooldown_hours} hours.", mention_author=False)
                
        except Exception as e:
            await ctx.reply(f"❌ Error claiming daily reward: {e}", mention_author=False)

    @economy_group.command(name="history", aliases=["transactions", "tx"])
    async def economy_history(self, ctx, member: discord.Member = None):
        """View transaction history"""
        target = member or ctx.author
        
        try:
            transactions = await self.economy_system.get_transaction_history(target.id, 20)
            if not transactions:
                await ctx.send(f"{target.display_name} has no transaction history.")
                return
            
            embed = discord.Embed(
                title=f"💰 Transaction History - {target.display_name}",
                color=discord.Color.blue()
            )
            
            history_text = ""
            for tx_type, amount, reason, date in transactions[:10]:
                emoji = "📈" if amount > 0 else "📉"
                sign = "+" if amount > 0 else ""
                history_text += f"{emoji} {sign}{amount:,} - {tx_type}"
                if reason:
                    history_text += f" ({reason})"
                history_text += f"\n*{date}*\n\n"
            
            embed.description = history_text[:2000]  # Discord limit
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving transaction history: {e}")
    
    @economy_group.command(name="stats", aliases=["gambling"])
    @app_commands.describe(member="The user to check stats for")
    async def gambling_stats(self, ctx, member: discord.Member = None):
        """View gambling statistics"""
        target = member or ctx.author
        
        try:
            stats = await self.economy_system.get_gambling_stats(target.id)
            if not stats:
                await ctx.reply(f"{target.display_name} has no gambling statistics.", mention_author=False)
                return
            
            embed = discord.Embed(
                title=f"🎲 Gambling Statistics - {target.display_name}",
                color=discord.Color.gold()
            )
            
            total_bet = 0
            total_won = 0
            total_lost = 0
            
            for game, bet_amount, win_amount, loss_amount, max_win in stats:
                total_bet += bet_amount
                total_won += win_amount
                total_lost += loss_amount
                
                net = win_amount - loss_amount
                embed.add_field(
                    name=f"🎮 {game.title()}",
                    value=f"Bet: {bet_amount:,}\nWon: {win_amount:,}\nLost: {loss_amount:,}\nNet: {net:+,}\nMax Win: {max_win:,}",
                    inline=True
                )
            
            embed.add_field(
                name="📊 Overall",
                value=f"Total Bet: {total_bet:,}\nTotal Won: {total_won:,}\nTotal Lost: {total_lost:,}\nNet P/L: {(total_won - total_lost):+,}",
                inline=False
            )
            
            await ctx.reply(embed=embed, mention_author=False)
            
        except Exception as e:
            await ctx.reply(f"❌ Error retrieving gambling statistics: {e}", mention_author=False)
    
    @economy_group.command(name="rakeback", aliases=["rb"])
    async def rakeback_command(self, ctx):
        """Check and claim rakeback balance"""
        try:
            balance = await self.economy_system.get_rakeback_info(ctx.author.id)
            
            if balance <= 0:
                await ctx.send("💸 You don't have any rakeback to claim.")
                return
            
            claimed = await self.economy_system.claim_rakeback(ctx.author.id)
            currency_symbol = await self.config.currency_symbol()
            
            embed = discord.Embed(
                title="💰 Rakeback Claimed!",
                description=f"You received {currency_symbol}{claimed:,} in rakeback!",
                color=discord.Color.green()
            )
            embed.add_field(
                name="ℹ️ About Rakeback",
                value="You earn 5% rakeback on gambling losses. Claim it anytime!",
                inline=False
            )
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error with rakeback: {e}")
    
    @economy_group.command(name="bank")
    async def bank_info(self, ctx, member: discord.Member = None):
        """View bank information"""
        target = member or ctx.author
        
        try:
            balance = await self.economy_system.get_bank_info(target.id)
            currency_symbol = await self.config.currency_symbol()
            
            embed = discord.Embed(
                title=f"🏦 Bank Account - {target.display_name}",
                color=discord.Color.blue()
            )
            embed.add_field(name="Balance", value=f"{currency_symbol}{balance:,}", inline=True)
            
            await ctx.reply(embed=embed, mention_author=False)
            
        except Exception as e:
            await ctx.reply(f"❌ Error retrieving bank information: {e}", mention_author=False)

    @economy_group.command(name="award")
    @checks.is_owner()
    async def economy_award(self, ctx, amount: int, member: discord.Member, *, note: str = ""):
        """Award Slut points to a user (owner only)"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        # Immediate length check to prevent DoS from massive input strings
        if len(note) > 200:
            await ctx.send("❌ Note is too long (max 200 chars).")
            return

        try:
            await self.economy_system.award_currency(member.id, amount, note)
            currency_symbol = await self.config.currency_symbol()
            await ctx.send(f"✅ Awarded {currency_symbol}{amount:,} to {member.mention}!")
            
        except Exception as e:
            await ctx.send(f"❌ Error awarding Slut points: {e}")
    
    @economy_group.command(name="take")
    @checks.is_owner()
    async def economy_take(self, ctx, amount: int, member: discord.Member, *, note: str = ""):
        """Take Slut points from a user (owner only)"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        # Immediate length check to prevent DoS from massive input strings
        if len(note) > 200:
            await ctx.send("❌ Note is too long (max 200 chars).")
            return

        try:
            success = await self.economy_system.take_currency(member.id, amount, note)
            if success:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"✅ Took {currency_symbol}{amount:,} from {member.mention}!")
            else:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"❌ {member.mention} doesn't have enough {currency_symbol} Slut points.")
                
        except Exception as e:
            await ctx.send(f"❌ Error taking Slut points: {e}")
    
    @economy_group.command(name="leaderboard", aliases=["lb", "top"])
    @commands.guild_only()
    async def economy_leaderboard(self, ctx):
        """Show the Slut points leaderboard"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        try:
            # Get filtered leaderboard (only members in server)
            top_users = await self.economy_system.get_filtered_leaderboard(ctx.guild)
            
            if not top_users:
                await ctx.send("No economy data found for this server.")
                return
            
            # Find user position
            user_position = None
            for i, (uid, _) in enumerate(top_users):
                if uid == ctx.author.id:
                    user_position = i
                    break
            
            currency_symbol = await self.config.currency_symbol()
            
            view = LeaderboardView(ctx, top_users, user_position, currency_symbol)
            embed = await view.get_embed()
            view.message = await ctx.reply(embed=embed, view=view, mention_author=False)
            
        except Exception as e:
            import logging
            log = logging.getLogger("red.unicornia")
            log.error(f"Error in economy leaderboard: {e}", exc_info=True)
            await ctx.send(f"❌ Error retrieving leaderboard: {e}")
    
    # Bank commands
    @commands.hybrid_group(name="bank")
    async def bank_group(self, ctx):
        """Bank commands for storing currency"""
        pass
    
    @bank_group.command(name="deposit", aliases=["dep"])
    async def bank_deposit(self, ctx, amount: int):
        """Deposit Slut points into your bank account"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        try:
            success = await self.economy_system.deposit_bank(ctx.author.id, amount)
            if success:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"✅ Deposited {currency_symbol}{amount:,} into your bank account!")
            else:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"❌ You don't have enough {currency_symbol} Slut points to deposit.")
                
        except Exception as e:
            await ctx.send(f"❌ Error depositing Slut points: {e}")
    
    @bank_group.command(name="withdraw", aliases=["with"])
    async def bank_withdraw(self, ctx, amount: int):
        """Withdraw Slut points from your bank account"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        try:
            success = await self.economy_system.withdraw_bank(ctx.author.id, amount)
            if success:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"✅ Withdrew {currency_symbol}{amount:,} from your bank account!")
            else:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"❌ You don't have enough {currency_symbol} Slut points in your bank account.")
                
        except Exception as e:
            await ctx.send(f"❌ Error withdrawing Slut points: {e}")
    
    @bank_group.command(name="balance", aliases=["bal"])
    async def bank_balance(self, ctx):
        """Check your bank balance"""
        if not await self.config.economy_enabled():
            await ctx.reply("❌ Economy system is disabled.", mention_author=False)
            return
        
        try:
            wallet_balance, bank_balance = await self.economy_system.get_balance(ctx.author.id)
            currency_symbol = await self.config.currency_symbol()
            await ctx.reply(f"🏦 Your bank balance: {currency_symbol}{bank_balance:,}", mention_author=False)
                
        except Exception as e:
            await ctx.reply(f"❌ Error retrieving bank balance: {e}", mention_author=False)
