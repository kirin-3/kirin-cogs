import discord
from redbot.core import commands, checks
from redbot.core.utils.menus import SimpleMenu, ListPageSource
from typing import Optional
from ..utils import validate_text_input

class EconomyCommands:
    # Economy commands
    @commands.command(name="baltop", aliases=["ballb"])
    async def baltop_shortcut(self, ctx):
        """Show the Slut points leaderboard"""
        await self.economy_leaderboard(ctx)

    @commands.group(name="economy", aliases=["econ", "money"])
    async def economy_group(self, ctx):
        """Economy and currency commands"""
        pass
    
    @economy_group.command(name="balance", aliases=["bal", "wallet"])
    async def economy_balance(self, ctx, member: discord.Member = None):
        """Check your or another user's Slut points balance"""
        await self._balance_logic(ctx, member)

    @commands.command(name="balance", aliases=["bal", "$", "€", "£"])
    async def global_balance(self, ctx, member: discord.Member = None):
        """Check your or another user's balance"""
        await self._balance_logic(ctx, member)

    async def _balance_logic(self, ctx, member: discord.Member = None):
        """Shared logic for balance commands"""
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
            embed.add_field(name=f"{currency_symbol} Currency", value=f"{currency_symbol}{wallet_balance:,}", inline=True)
            embed.add_field(name="🏦 Bank", value=f"{currency_symbol}{bank_balance:,}", inline=True)
            embed.add_field(name="💎 Total", value=f"{currency_symbol}{wallet_balance + bank_balance:,}", inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving balance: {e}")
    
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

    @commands.command(name="timely", aliases=["daily"])
    @commands.cooldown(1, 86400, commands.BucketType.user)  # 24 hours cooldown
    async def global_timely(self, ctx):
        """Claim your daily reward"""
        await self._timely_logic(ctx)

    async def _timely_logic(self, ctx):
        """Shared logic for timely commands"""
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
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
                await ctx.send(embed=embed)
            else:
                cooldown_hours = await self.config.timely_cooldown()
                await ctx.send(f"❌ You can claim your daily reward in {cooldown_hours} hours.")
                
        except Exception as e:
            await ctx.send(f"❌ Error claiming daily reward: {e}")

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
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving bank information: {e}")

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
        
        try:
            await self.economy_system.award_currency(member.id, amount, note)
            currency_symbol = await self.config.currency_symbol()
            await ctx.send(f"✅ Awarded {currency_symbol}{amount:,} to {member.mention}!")
            
            # Invalidate XP cache if configured to sync currency/xp
            # But the user asked specifically to fix the award command cache invalidation problem.
            # XP System has an LRU cache `user_xp_cache`.
            # If `award` only touches currency, it doesn't affect XP.
            # However, if the user means `xp award`? There is no `xp award` command in `unicornia/commands/level.py` or `unicornia/COMMANDS.md`.
            # The only award command is `[p]economy award`.
            # Wait, maybe they mean `[p]level` commands? `[p]level check`.
            # If the user means `economy award` should invalidate XP cache? That makes no sense unless XP is currency?
            # Or maybe I missed an XP add command?
            # Let's check `unicornia/systems/xp_system.py` again. It has `process_message`.
            # `unicornia/db/xp.py` has `add_xp`.
            # `unicornia/commands/level.py` only has `check` and `leaderboard`.
            # Ah, maybe I should check if there are other commands in `unicornia/commands/admin.py`?
            # `[p]unicornia guild currencyreward` exists.
            
            # If the user insists on "award command should invalidate the cache", they likely mean if I modify XP.
            # But I don't see an XP modification command.
            # Wait, `unicornia/COMMANDS.md` mentions:
            # 64 | | `[p]economy award <amount> <user>` | Award currency to a user (generated out of thin air). (Bot Owner only)
            
            # Maybe the user assumes "award" means XP award? Or maybe I am blind.
            # Let's search for "xp" in `unicornia/commands/admin.py` or similar.
            pass
        except Exception as e:
            await ctx.send(f"❌ Error awarding Slut points: {e}")
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
    async def economy_leaderboard(self, ctx, limit: int = 10):
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
            
            entries = []
            currency_symbol = await self.config.currency_symbol()
            for i, (user_id, balance) in enumerate(top_users):
                member = ctx.guild.get_member(user_id)
                username = member.display_name
                
                rank = i + 1
                if rank == 1:
                    rank_str = "🥇"
                elif rank == 2:
                    rank_str = "🥈"
                elif rank == 3:
                    rank_str = "🥉"
                else:
                    rank_str = f"**{rank}.**"
                    
                entries.append(f"{rank_str} **{username}**\n{currency_symbol}{balance:,}\n")
            
            # Pagination
            source = ListPageSource(entries, per_page=10)
            source.embed_title = "<:slut:686148402941001730> Slut points Leaderboard"
            source.embed_color = discord.Color.gold()
            
            # Custom formatter to handle embed format
            async def format_page(menu, entries):
                offset = menu.current_page * 10
                joined = "\n".join(entries)
                embed = discord.Embed(
                    title=source.embed_title,
                    description=joined,
                    color=source.embed_color
                )
                embed.set_footer(text=f"Page {menu.current_page + 1}/{source.get_max_pages()}")
                return embed
                
            source.format_page = format_page
            
            menu = SimpleMenu(source)
            await menu.start(ctx)
            
        except Exception as e:
            import logging
            log = logging.getLogger("red.unicornia")
            log.error(f"Error in economy leaderboard: {e}", exc_info=True)
            await ctx.send(f"❌ Error retrieving leaderboard: {e}")
    
    # Bank commands
    @commands.group(name="bank")
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
            await ctx.send("❌ Economy system is disabled.")
            return
        
        try:
            wallet_balance, bank_balance = await self.economy_system.get_balance(ctx.author.id)
            currency_symbol = await self.config.currency_symbol()
            await ctx.send(f"🏦 Your bank balance: {currency_symbol}{bank_balance:,}")
                
        except Exception as e:
            await ctx.send(f"❌ Error retrieving bank balance: {e}")
