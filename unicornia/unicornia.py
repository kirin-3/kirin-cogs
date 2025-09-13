"""
Unicornia - Full-Featured Leveling and Economy Cog

A Red bot cog that provides complete leveling and economy features similar to Nadeko.
Includes XP gain, currency transactions, gambling, banking, shop, and more.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import humanize_number, box

from .database import DatabaseManager
from .xp_system import XPSystem
from .economy_system import EconomySystem
from .gambling_system import GamblingSystem
from .currency_systems import CurrencyGeneration, CurrencyDecay

log = logging.getLogger("red.unicornia")


class Unicornia(commands.Cog):
    """Full-featured leveling and economy cog with Nadeko-like functionality"""
    
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        
        # Default configuration
        default_global = {
            "currency_name": "Unicorn Coins",
            "currency_symbol": "🦄",
            "xp_enabled": True,
            "economy_enabled": True,
            "gambling_enabled": True,
            "shop_enabled": True,
            "timely_amount": 100,
            "timely_cooldown": 24,  # hours
            "xp_per_message": 1,
            "xp_cooldown": 60,  # seconds
            # Currency generation
            "currency_generation_enabled": False,
            "generation_chance": 0.02,  # 2%
            "generation_cooldown": 10,  # seconds
            "generation_min_amount": 1,
            "generation_max_amount": 1,
            "generation_has_password": True,
            # Currency decay
            "decay_percent": 0.0,  # 0% (disabled by default)
            "decay_max_amount": 0,  # unlimited
            "decay_min_threshold": 99,
            "decay_hour_interval": 24
        }
        
        default_guild = {
            "xp_enabled": True,
            "level_up_messages": True,
            "level_up_channel": None,
            "role_rewards": {},  # {level: role_id}
            "currency_rewards": {},  # {level: amount}
            "excluded_channels": [],
            "excluded_roles": []
        }
        
        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)
        
        # Initialize systems (will be properly initialized in cog_load)
        self.db = None
        self.xp_system = None
        self.economy_system = None
        self.gambling_system = None
        self.currency_generation = None
        self.currency_decay = None
    
    async def cog_load(self):
        """Called when the cog is loaded - proper async initialization"""
        try:
            # Initialize database first
            # Look for Nadeko database in the same directory as this cog
            import os
            cog_dir = os.path.dirname(os.path.abspath(__file__))
            nadeko_db_path = os.path.join(cog_dir, "nadeko.db")
            self.db = DatabaseManager("data/unicornia.db", nadeko_db_path)
            await self.db.initialize()
            
            # Migrate data from Nadeko database
            await self.db.migrate_from_nadeko()
            
            # Initialize all systems
            self.xp_system = XPSystem(self.db, self.config, self.bot)
            self.economy_system = EconomySystem(self.db, self.config, self.bot)
            self.gambling_system = GamblingSystem(self.db, self.config, self.bot)
            self.currency_generation = CurrencyGeneration(self.db, self.config, self.bot)
            self.currency_decay = CurrencyDecay(self.db, self.config, self.bot)
            
            # Start background tasks
            await self.currency_decay.start_decay_loop()
            
            # Start WAL maintenance task
            asyncio.create_task(self._wal_maintenance_loop())
            
            log.info("Unicornia: All systems initialized successfully")
        except Exception as e:
            log.error(f"Unicornia: Failed to initialize: {e}")
            raise
    
    async def cog_unload(self):
        """Called when the cog is unloaded - proper cleanup"""
        try:
            if self.currency_decay:
                await self.currency_decay.stop_decay_loop()
            log.info("Unicornia: Cog unloaded successfully")
        except Exception as e:
            log.error(f"Unicornia: Error during unload: {e}")
    
    def _check_systems_ready(self) -> bool:
        """Check if all systems are properly initialized"""
        return all([
            self.db is not None,
            self.xp_system is not None,
            self.economy_system is not None,
            self.gambling_system is not None,
            self.currency_generation is not None,
            self.currency_decay is not None
        ])
    
    async def _wal_maintenance_loop(self):
        """Periodic WAL maintenance to prevent corruption and optimize performance"""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                if self.db:
                    await self.db.check_wal_integrity()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"WAL maintenance error: {e}")
                await asyncio.sleep(300)  # Wait 5 minutes before retrying
    
    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle XP gain and currency generation from messages"""
        if message.author.bot or not message.guild:
            return
        
        # Check if systems are initialized
        if not self._check_systems_ready():
            return
        
        # Process XP gain
        await self.xp_system.process_message(message)
        
        # Process currency generation
        await self.currency_generation.process_message(message)
    
    # Main command groups
    @commands.group(name="unicornia", aliases=["uni"])
    async def unicornia_group(self, ctx):
        """Unicornia - Full-featured leveling and economy system"""
        pass
    
    @commands.group(name="xpshop", aliases=["xps"])
    async def xp_shop_group(self, ctx):
        """XP Shop - Buy custom backgrounds with currency"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    
    @xp_shop_group.command(name="backgrounds", aliases=["bg", "bgs"])
    async def shop_backgrounds(self, ctx):
        """View available XP backgrounds"""
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            backgrounds = self.xp_system.card_generator.get_available_backgrounds()
            user_owned = await self.db.get_user_xp_items(ctx.author.id, 1)  # 1 = Background
            owned_keys = {item[3] for item in user_owned}  # ItemKey
            
            embed = discord.Embed(
                title="🖼️ XP Backgrounds Shop",
                description="Purchase backgrounds with your currency!",
                color=discord.Color.blue()
            )
            
            for key, bg_data in backgrounds.items():
                name = bg_data.get('name', key)
                price = bg_data.get('price', -1)
                desc = bg_data.get('desc', '')
                
                if price == -1:
                    continue  # Skip removed items
                
                owned_text = " ✅ **OWNED**" if key in owned_keys else ""
                price_text = "FREE" if price == 0 else f"{price:,} 🪙"
                
                embed.add_field(
                    name=f"{name}{owned_text}",
                    value=f"Price: {price_text}\n{desc}",
                    inline=True
                )
            
            user_currency = await self.db.get_user_currency(ctx.author.id)
            embed.set_footer(text=f"Your currency: {user_currency:,} 🪙")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error loading backgrounds: {e}")
    
    @xp_shop_group.command(name="buy")
    async def shop_buy(self, ctx, item_key: str):
        """Buy an XP background
        
        Usage: 
        - `[p]xpshop buy default` - Buy default background
        - `[p]xpshop buy shadow` - Buy shadow background
        """
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            # Get background info
            items = self.xp_system.card_generator.get_available_backgrounds()
            price = self.xp_system.card_generator.get_background_price(item_key)
            
            if item_key not in items:
                await ctx.send(f"❌ Background `{item_key}` not found.")
                return
            
            if price == -1:
                await ctx.send(f"❌ Background `{item_key}` is no longer available for purchase.")
                return
            
            # Attempt purchase (item_type_id = 1 for backgrounds)
            success = await self.db.purchase_xp_item(ctx.author.id, 1, item_key, price)
            
            if success:
                item_name = items[item_key].get('name', item_key)
                price_text = "FREE" if price == 0 else f"{price:,} 🪙"
                await ctx.send(f"✅ Successfully purchased **{item_name}** for {price_text}!")
            else:
                # Check why it failed
                if await self.db.user_owns_xp_item(ctx.author.id, 1, item_key):
                    await ctx.send(f"❌ You already own this background!")
                else:
                    user_currency = await self.db.get_user_currency(ctx.author.id)
                    await ctx.send(f"❌ Insufficient currency! You have {user_currency:,} 🪙 but need {price:,} 🪙.")
            
        except Exception as e:
            await ctx.send(f"❌ Error processing purchase: {e}")
    
    @xp_shop_group.command(name="reload")
    @commands.is_owner()
    async def shop_reload_config(self, ctx):
        """Reload XP shop configuration (Owner only)"""
        try:
            await self.xp_system.card_generator._load_xp_config()
            await ctx.send("✅ XP shop configuration reloaded successfully!")
        except Exception as e:
            await ctx.send(f"❌ Error reloading configuration: {e}")
    
    @xp_shop_group.command(name="config")
    @commands.is_owner()
    async def shop_config_info(self, ctx):
        """Show XP shop configuration file location (Owner only)"""
        config_path = os.path.join(self.xp_system.card_generator.cog_dir, "xp_config.yml")
        embed = discord.Embed(
            title="🔧 XP Shop Configuration",
            description=f"Configuration file location:\n`{config_path}`",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="How to add/edit backgrounds:",
            value="1. Edit the `xp_config.yml` file\n2. Add new backgrounds under `shop.bgs`\n3. Use `[p]xpshop reload` to apply changes",
            inline=False
        )
        embed.add_field(
            name="Background format:",
            value="```yaml\nkey_name:\n  name: Display Name\n  price: 10000\n  url: https://your-image-url.com/image.gif\n  desc: Optional description```",
            inline=False
        )
        embed.add_field(
            name="Note:",
            value="All users start with the 'default' background. They can purchase additional backgrounds with currency.",
            inline=False
        )
        await ctx.send(embed=embed)
    
    @unicornia_group.command(name="status")
    async def status(self, ctx):
        """Check Unicornia status and configuration"""
        embed = discord.Embed(
            title="🦄 Unicornia Status",
            color=discord.Color.green(),
            description="Full-featured leveling and economy system"
        )
        
        xp_enabled = await self.config.xp_enabled()
        economy_enabled = await self.config.economy_enabled()
        gambling_enabled = await self.config.gambling_enabled()
        shop_enabled = await self.config.shop_enabled()
        
        embed.add_field(name="XP System", value="✅ Enabled" if xp_enabled else "❌ Disabled", inline=True)
        embed.add_field(name="Economy System", value="✅ Enabled" if economy_enabled else "❌ Disabled", inline=True)
        embed.add_field(name="Gambling", value="✅ Enabled" if gambling_enabled else "❌ Disabled", inline=True)
        embed.add_field(name="Shop", value="✅ Enabled" if shop_enabled else "❌ Disabled", inline=True)
        
        currency_name = await self.config.currency_name()
        currency_symbol = await self.config.currency_symbol()
        embed.add_field(name="Currency", value=f"{currency_symbol} {currency_name}", inline=True)
        
        timely_amount = await self.config.timely_amount()
        timely_cooldown = await self.config.timely_cooldown()
        embed.add_field(name="Daily Reward", value=f"{currency_symbol}{timely_amount} every {timely_cooldown}h", inline=True)
        
        await ctx.send(embed=embed)
    
    # Level commands
    @commands.group(name="level", aliases=["lvl", "xp"])
    async def level_group(self, ctx):
        """Level and XP commands"""
        pass
    
    @level_group.command(name="check", aliases=["me"])
    async def level_check(self, ctx, member: discord.Member = None):
        """Check your or another user's level and XP"""
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        if not await self.config.xp_enabled():
            await ctx.send("❌ XP system is disabled.")
            return
        
        member = member or ctx.author
        
        try:
            level_stats = await self.xp_system.get_user_level_stats(member.id, ctx.guild.id)
            
            embed = discord.Embed(
                title=f"{member.display_name}'s Level",
                color=member.color or discord.Color.blue()
            )
            embed.add_field(name="Level", value=level_stats.level, inline=True)
            embed.add_field(name="XP", value=f"{level_stats.level_xp:,}/{level_stats.required_xp:,}", inline=True)
            embed.add_field(name="Total XP", value=f"{level_stats.total_xp:,}", inline=True)
            
            # Progress bar
            progress_bar = self.xp_system.get_progress_bar(level_stats.level_xp, level_stats.required_xp)
            embed.add_field(name="Progress", value=f"`{progress_bar}` {level_stats.level_xp/level_stats.required_xp:.1%}", inline=False)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving level data: {e}")
    
    @level_group.command(name="leaderboard", aliases=["lb", "top"])
    async def level_leaderboard(self, ctx, limit: int = 10):
        """Show the XP leaderboard for this server"""
        if not await self.config.xp_enabled():
            await ctx.send("❌ XP system is disabled.")
            return
        
        try:
            top_users = await self.xp_system.get_leaderboard(ctx.guild.id, limit)
            
            if not top_users:
                await ctx.send("No XP data found for this server.")
                return
            
            entries = []
            for i, (user_id, xp) in enumerate(top_users):
                member = ctx.guild.get_member(user_id)
                username = member.display_name if member else f"Unknown User ({user_id})"
                level_stats = self.db.calculate_level_stats(xp)
                entries.append(f"**{i + 1}.** {username} - Level **{level_stats.level}** ({xp:,} XP)")
            
            embed = discord.Embed(
                title=f"XP Leaderboard - {ctx.guild.name}",
                description="\n".join(entries),
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving leaderboard: {e}")
    
    # Economy commands
    @commands.group(name="economy", aliases=["econ", "money"])
    async def economy_group(self, ctx):
        """Economy and currency commands"""
        pass
    
    @economy_group.command(name="balance", aliases=["bal", "wallet"])
    async def economy_balance(self, ctx, member: discord.Member = None):
        """Check your or another user's wallet and bank balance"""
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
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
    
    @economy_group.command(name="award")
    @checks.is_owner()
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
    
    # Gambling commands
    @commands.group(name="gambling", aliases=["gamble"])
    async def gambling_group(self, ctx):
        """Gambling commands"""
        pass
    
    @gambling_group.command(name="betroll", aliases=["roll"])
    async def gambling_betroll(self, ctx, amount: int):
        """Bet on a dice roll (1-100)"""
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        try:
            success, result = await self.gambling_system.betroll(ctx.author.id, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.send(f"❌ You don't have enough {currency_symbol}currency. You have {currency_symbol}{result['balance']:,}.")
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
    async def gambling_rps(self, ctx, choice: str, amount: int = 0):
        """Play rock paper scissors"""
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        try:
            success, result = await self.gambling_system.rock_paper_scissors(ctx.author.id, choice, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.send(f"❌ You don't have enough {currency_symbol}currency. You have {currency_symbol}{result['balance']:,}.")
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
                    await ctx.send(f"{result['user_choice']} vs {result['bot_choice']} - It's a draw! No money lost.")
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
    async def gambling_slots(self, ctx, amount: int):
        """Play slots"""
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        try:
            success, result = await self.gambling_system.slots(ctx.author.id, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.send(f"❌ You don't have enough {currency_symbol}currency. You have {currency_symbol}{result['balance']:,}.")
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
    
    @gambling_group.command(name="luckyladder", aliases=["ladder"])
    async def gambling_lucky_ladder(self, ctx, amount: int):
        """Play lucky ladder"""
        if not await self.config.gambling_enabled():
            await ctx.send("❌ Gambling is disabled.")
            return
        
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if amount <= 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        try:
            success, result = await self.gambling_system.lucky_ladder(ctx.author.id, amount)
            if not success:
                if result.get("error") == "insufficient_funds":
                    currency_symbol = await self.config.currency_symbol()
                    await ctx.send(f"❌ You don't have enough {currency_symbol}currency. You have {currency_symbol}{result['balance']:,}.")
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
    
    # Currency generation commands
    @commands.group(name="currency")
    async def currency_group(self, ctx):
        """Currency generation and management commands"""
        pass
    
    @currency_group.command(name="pick")
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
    
    # Configuration commands
    @unicornia_group.command(name="config")
    @checks.is_owner()
    async def config_cmd(self, ctx, setting: str, *, value: str):
        """Configure Unicornia settings"""
        valid_settings = [
            "currency_name", "currency_symbol", "xp_enabled", "economy_enabled", 
            "gambling_enabled", "shop_enabled", "timely_amount", "timely_cooldown", 
            "xp_per_message", "xp_cooldown", "currency_generation_enabled",
            "generation_chance", "generation_cooldown", "generation_min_amount",
            "generation_max_amount", "generation_has_password", "decay_percent",
            "decay_max_amount", "decay_min_threshold", "decay_hour_interval"
        ]
        
        if setting not in valid_settings:
            await ctx.send(f"Invalid setting. Valid options: {', '.join(valid_settings)}")
            return
        
        try:
            if setting in ["xp_enabled", "economy_enabled", "gambling_enabled", "shop_enabled", "currency_generation_enabled", "generation_has_password"]:
                enabled = value.lower() in ["true", "yes", "1", "on"]
                await getattr(self.config, setting).set(enabled)
                await ctx.send(f"✅ {setting} {'enabled' if enabled else 'disabled'}")
            elif setting in ["timely_amount", "timely_cooldown", "xp_per_message", "xp_cooldown", "generation_cooldown", "generation_min_amount", "generation_max_amount", "decay_max_amount", "decay_min_threshold", "decay_hour_interval"]:
                amount = int(value)
                if amount < 0:
                    await ctx.send("❌ Amount must be positive.")
                    return
                await getattr(self.config, setting).set(amount)
                await ctx.send(f"✅ {setting} updated to {amount}")
            elif setting == "generation_chance":
                chance = float(value)
                if not 0 <= chance <= 1:
                    await ctx.send("❌ Chance must be between 0 and 1.")
                    return
                await getattr(self.config, setting).set(chance)
                await ctx.send(f"✅ {setting} updated to {chance}")
            elif setting == "decay_percent":
                percent = float(value)
                if not 0 <= percent <= 1:
                    await ctx.send("❌ Decay percent must be between 0 and 1.")
                    return
                await getattr(self.config, setting).set(percent)
                await ctx.send(f"✅ {setting} updated to {percent}")
            else:
                await getattr(self.config, setting).set(value)
                await ctx.send(f"✅ {setting} updated to {value}")
                
        except ValueError:
            await ctx.send("❌ Invalid value type for this setting.")
        except Exception as e:
            await ctx.send(f"❌ Error updating setting: {e}")
    
    @unicornia_group.group(name="guild")
    @checks.admin()
    async def guild_config(self, ctx):
        """Guild-specific configuration"""
        pass
    
    @guild_config.command(name="xpenabled")
    async def guild_xp_enabled(self, ctx, enabled: bool):
        """Enable/disable XP system for this guild"""
        await self.config.guild(ctx.guild).xp_enabled.set(enabled)
        await ctx.send(f"✅ XP system {'enabled' if enabled else 'disabled'} for this guild.")
    
    @guild_config.command(name="levelupmessages")
    async def guild_level_up_messages(self, ctx, enabled: bool):
        """Enable/disable level up messages for this guild"""
        await self.config.guild(ctx.guild).level_up_messages.set(enabled)
        await ctx.send(f"✅ Level up messages {'enabled' if enabled else 'disabled'} for this guild.")
    
    @guild_config.command(name="levelupchannel")
    async def guild_level_up_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel for level up messages (leave empty for current channel)"""
        channel = channel or ctx.channel
        await self.config.guild(ctx.guild).level_up_channel.set(channel.id)
        await ctx.send(f"✅ Level up messages will be sent to {channel.mention}")
    
    @guild_config.command(name="excludechannel")
    async def guild_exclude_channel(self, ctx, channel: discord.TextChannel):
        """Exclude a channel from XP gain"""
        excluded = await self.config.guild(ctx.guild).excluded_channels()
        if channel.id not in excluded:
            excluded.append(channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(excluded)
            await ctx.send(f"✅ {channel.mention} excluded from XP gain.")
        else:
            await ctx.send(f"❌ {channel.mention} is already excluded from XP gain.")
    
    @guild_config.command(name="includechannel")
    async def guild_include_channel(self, ctx, channel: discord.TextChannel):
        """Include a channel in XP gain"""
        excluded = await self.config.guild(ctx.guild).excluded_channels()
        if channel.id in excluded:
            excluded.remove(channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(excluded)
            await ctx.send(f"✅ {channel.mention} included in XP gain.")
        else:
            await ctx.send(f"❌ {channel.mention} is not excluded from XP gain.")
    
    @guild_config.command(name="rolereward")
    async def guild_role_reward(self, ctx, level: int, role: discord.Role):
        """Set a role reward for reaching a level"""
        if level < 1:
            await ctx.send("❌ Level must be at least 1.")
            return
        
        role_rewards = await self.config.guild(ctx.guild).role_rewards()
        role_rewards[str(level)] = role.id
        await self.config.guild(ctx.guild).role_rewards.set(role_rewards)
        await ctx.send(f"✅ Users reaching level {level} will receive the {role.mention} role.")
    
    @guild_config.command(name="currencyreward")
    async def guild_currency_reward(self, ctx, level: int, amount: int):
        """Set a currency reward for reaching a level"""
        if level < 1:
            await ctx.send("❌ Level must be at least 1.")
            return
        
        if amount < 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        currency_rewards = await self.config.guild(ctx.guild).currency_rewards()
        currency_rewards[str(level)] = amount
        await self.config.guild(ctx.guild).currency_rewards.set(currency_rewards)
        currency_symbol = await self.config.currency_symbol()
        await ctx.send(f"✅ Users reaching level {level} will receive {currency_symbol}{amount:,}.")