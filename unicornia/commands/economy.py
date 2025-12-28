import discord
from redbot.core import commands, checks
from typing import Optional
from ..utils import systems_ready

class EconomyCommands:
    # Economy commands
    @commands.group(name="economy", aliases=["econ", "money"])
    async def economy_group(self, ctx):
        """Economy and currency commands"""
        pass
    
    @economy_group.command(name="balance", aliases=["bal", "wallet"])
    @systems_ready
    async def economy_balance(self, ctx, member: discord.Member = None):
        """Check your or another user's wallet and bank balance"""
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        member = member or ctx.author
        
        try:
            wallet_balance, bank_balance = await self.economy_system.get_balance(member.id)
            currency_symbol = await self.config.currency_symbol()
            
            embed = discord.Embed(
                title=f"{member.display_name}'s Balance",
                color=member.color or discord.Color.green()
            )
            embed.add_field(name="💰 Wallet", value=f"{currency_symbol}{wallet_balance:,}", inline=True)
            embed.add_field(name="🏦 Bank", value=f"{currency_symbol}{bank_balance:,}", inline=True)
            embed.add_field(name="💎 Total", value=f"{currency_symbol}{wallet_balance + bank_balance:,}", inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving balance: {e}")
    
    @economy_group.command(name="give")
    @systems_ready
    async def economy_give(self, ctx, amount: int, member: discord.Member, *, note: str = ""):
        """Give currency to another user"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        if member.bot:
            await ctx.send("❌ You can't give currency to bots.")
            return
        
        if member == ctx.author:
            await ctx.send("❌ You can't give currency to yourself.")
            return
        
        try:
            success = await self.economy_system.give_currency(ctx.author.id, member.id, amount, note)
            if success:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"✅ You gave {currency_symbol}{amount:,} to {member.mention}!")
            else:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"❌ You don't have enough {currency_symbol}currency.")
                
        except Exception as e:
            await ctx.send(f"❌ Error transferring currency: {e}")
    
    @economy_group.command(name="timely", aliases=["daily"])
    @commands.cooldown(1, 86400, commands.BucketType.user)  # 24 hours cooldown
    @systems_ready
    async def economy_timely(self, ctx):
        """Claim your daily currency reward"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        try:
            if await self.economy_system.claim_timely(ctx.author.id):
                amount = await self.config.timely_amount()
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"✅ You claimed your daily reward of {currency_symbol}{amount:,}!")
            else:
                cooldown_hours = await self.config.timely_cooldown()
                await ctx.send(f"❌ You can claim your daily reward in {cooldown_hours} hours.")
                
        except Exception as e:
            await ctx.send(f"❌ Error claiming daily reward: {e}")
    
    @economy_group.command(name="history", aliases=["transactions", "tx"])
    @systems_ready
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
    @systems_ready
    async def gambling_stats(self, ctx, member: discord.Member = None):
        """View gambling statistics"""
        target = member or ctx.author
        
        try:
            stats = await self.economy_system.get_gambling_stats(target.id)
            if not stats:
                await ctx.send(f"{target.display_name} has no gambling statistics.")
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
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving gambling statistics: {e}")
    
    @economy_group.command(name="rakeback", aliases=["rb"])
    @systems_ready
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
    @systems_ready
    async def bank_info(self, ctx, member: discord.Member = None):
        """View bank information"""
        target = member or ctx.author
        
        try:
            balance, interest_rate = await self.economy_system.get_bank_info(target.id)
            currency_symbol = await self.config.currency_symbol()
            
            embed = discord.Embed(
                title=f"🏦 Bank Account - {target.display_name}",
                color=discord.Color.blue()
            )
            embed.add_field(name="Balance", value=f"{currency_symbol}{balance:,}", inline=True)
            embed.add_field(name="Interest Rate", value=f"{interest_rate:.1%} per day", inline=True)
            
            # Calculate daily interest
            daily_interest = int(balance * interest_rate)
            if daily_interest > 0:
                embed.add_field(name="Daily Interest", value=f"{currency_symbol}{daily_interest:,}", inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving bank information: {e}")

    @economy_group.command(name="award")
    @checks.is_owner()
    @systems_ready
    async def economy_award(self, ctx, amount: int, member: discord.Member, *, note: str = ""):
        """Award currency to a user (owner only)"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        try:
            await self.economy_system.award_currency(member.id, amount, note)
            currency_symbol = await self.config.currency_symbol()
            await ctx.send(f"✅ Awarded {currency_symbol}{amount:,} to {member.mention}!")
            
        except Exception as e:
            await ctx.send(f"❌ Error awarding currency: {e}")
    
    @economy_group.command(name="take")
    @checks.is_owner()
    @systems_ready
    async def economy_take(self, ctx, amount: int, member: discord.Member, *, note: str = ""):
        """Take currency from a user (owner only)"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        try:
            success = await self.economy_system.take_currency(member.id, amount, note)
            if success:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"✅ Took {currency_symbol}{amount:,} from {member.mention}!")
            else:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"❌ {member.mention} doesn't have enough {currency_symbol}currency.")
                
        except Exception as e:
            await ctx.send(f"❌ Error taking currency: {e}")
    
    @economy_group.command(name="leaderboard", aliases=["lb", "top"])
    @systems_ready
    async def economy_leaderboard(self, ctx, limit: int = 10):
        """Show the currency leaderboard"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        try:
            top_users = await self.economy_system.get_leaderboard(limit)
            
            if not top_users:
                await ctx.send("No economy data found.")
                return
            
            entries = []
            currency_symbol = await self.config.currency_symbol()
            for i, (user_id, balance) in enumerate(top_users):
                member = ctx.guild.get_member(user_id) or self.bot.get_user(user_id)
                username = member.display_name if member else f"Unknown User ({user_id})"
                entries.append(f"**{i + 1}.** {username} - {currency_symbol}{balance:,}")
            
            embed = discord.Embed(
                title="Currency Leaderboard",
                description="\n".join(entries),
                color=discord.Color.gold()
            )
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving leaderboard: {e}")
    
    # Bank commands
    @commands.group(name="bank")
    async def bank_group(self, ctx):
        """Bank commands for storing currency"""
        pass
    
    @bank_group.command(name="deposit", aliases=["dep"])
    @systems_ready
    async def bank_deposit(self, ctx, amount: int):
        """Deposit currency into your bank account"""
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
                await ctx.send(f"❌ You don't have enough {currency_symbol}currency to deposit.")
                
        except Exception as e:
            await ctx.send(f"❌ Error depositing currency: {e}")
    
    @bank_group.command(name="withdraw", aliases=["with"])
    @systems_ready
    async def bank_withdraw(self, ctx, amount: int):
        """Withdraw currency from your bank account"""
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
                await ctx.send(f"❌ You don't have enough {currency_symbol}currency in your bank account.")
                
        except Exception as e:
            await ctx.send(f"❌ Error withdrawing currency: {e}")
    
    @bank_group.command(name="balance", aliases=["bal"])
    @systems_ready
    async def bank_balance(self, ctx):
        """Check your bank balance"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        try:
            wallet_balance, bank_balance = await self.economy_system.get_balance(ctx.author.id)
            currency_symbol = await self.config.currency_symbol()
            await ctx.send(f"🏦 Your bank balance: {currency_symbol}{bank_balance:,}")
                
        except Exception as e:
            await ctx.send(f"❌ Error retrieving bank balance: {e}")
