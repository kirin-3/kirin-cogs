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
from .shop_system import ShopSystem

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
            self.shop_system = ShopSystem(self.db, self.config, self.bot)
            
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
    
    async def cog_command_error(self, ctx, error):
        """Handle command errors with proper Red bot patterns"""
        # See: https://docs.discord-red.com/en/stable/framework_commands.html
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"❌ Command is on cooldown. Try again in {error.retry_after:.1f} seconds.")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command.")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send("❌ I don't have the required permissions to execute this command.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: {error.param.name}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Invalid argument: {error}")
        elif isinstance(error, commands.CommandNotFound):
            return  # Don't respond to unknown commands
        else:
            # Log unexpected errors
            log.error(f"Unexpected error in {ctx.command}: {error}", exc_info=True)
            await ctx.send("❌ An unexpected error occurred. Please try again later.")
    
    async def red_get_data_for_user(self, *, user_id: int):
        """Get user data for data export/deletion (Red bot requirement)"""
        # See: https://docs.discord-red.com/en/stable/framework_commands.html
        try:
            if not self._check_systems_ready():
                return {}
            
            # Get user's data from all systems
            data = {}
            
            # XP data
            xp_data = await self.db.get_user_xp_stats(user_id)
            if xp_data:
                data['xp_stats'] = xp_data
            
            # Currency data
            currency = await self.db.get_user_currency(user_id)
            if currency > 0:
                data['currency'] = currency
            
            # Bank data
            bank_data = await self.db.get_bank_user(user_id)
            if bank_data:
                data['bank'] = bank_data
            
            # Waifu data
            waifus = await self.db.get_user_waifus(user_id)
            if waifus:
                data['waifus'] = waifus
            
            # Transaction history
            transactions = await self.db.get_user_transactions(user_id, limit=100)
            if transactions:
                data['transactions'] = transactions
            
            return data
            
        except Exception as e:
            log.error(f"Error getting user data for {user_id}: {e}")
            return {}
    
    async def red_delete_data_for_user(self, *, requester: str, user_id: int):
        """Delete user data (Red bot requirement)"""
        # See: https://docs.discord-red.com/en/stable/framework_commands.html
        try:
            if not self._check_systems_ready():
                return
            
            # Delete user data from all systems
            await self.db.delete_user_data(user_id)
            
            log.info(f"Deleted data for user {user_id} (requested by {requester})")
            
        except Exception as e:
            log.error(f"Error deleting user data for {user_id}: {e}")
            raise
    
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
            
        except (OSError, IOError) as e:
            log.error(f"Error loading XP backgrounds: {e}")
            await ctx.send("❌ Error loading backgrounds. Please check the configuration file.")
        except Exception as e:
            log.error(f"Unexpected error loading backgrounds: {e}", exc_info=True)
            await ctx.send("❌ An unexpected error occurred while loading backgrounds.")
    
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
    
    @xp_shop_group.command(name="use")
    async def shop_use(self, ctx, item_key: str):
        """Set an XP background as active
        
        Usage: 
        - `[p]xpshop use default` - Use default background
        - `[p]xpshop use shadow` - Use shadow background (must own it first)
        """
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            # Check if user owns the background
            if not await self.db.user_owns_xp_item(ctx.author.id, 1, item_key):
                await ctx.send(f"❌ You don't own the background `{item_key}`. Purchase it first with `[p]xpshop buy {item_key}`.")
                return
            
            # Set as active
            success = await self.db.set_active_xp_item(ctx.author.id, 1, item_key)
            
            if success:
                backgrounds = self.xp_system.card_generator.get_available_backgrounds()
                item_name = backgrounds.get(item_key, {}).get('name', item_key)
                await ctx.send(f"✅ Now using **{item_name}** as your XP background!")
            else:
                await ctx.send(f"❌ Failed to set background. Make sure you own `{item_key}`.")
                
        except Exception as e:
            await ctx.send(f"❌ Error setting background: {e}")
    
    @xp_shop_group.command(name="owned", aliases=["inventory", "inv"])
    async def shop_owned(self, ctx):
        """View your owned XP backgrounds"""
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            owned_items = await self.db.get_user_xp_items(ctx.author.id, 1)  # 1 = Background
            backgrounds = self.xp_system.card_generator.get_available_backgrounds()
            
            if not owned_items:
                await ctx.send("❌ You don't own any backgrounds yet. Use `[p]xpshop backgrounds` to see what's available!")
                return
            
            embed = discord.Embed(
                title="🎒 Your XP Backgrounds",
                description="Backgrounds you own",
                color=discord.Color.green()
            )
            
            active_background = await self.db.get_active_xp_item(ctx.author.id, 1)
            
            for item in owned_items:
                item_key = item[3]  # ItemKey from database
                bg_data = backgrounds.get(item_key, {})
                name = bg_data.get('name', item_key)
                desc = bg_data.get('desc', '')
                
                status = " 🌟 **ACTIVE**" if item_key == active_background else ""
                
                embed.add_field(
                    name=f"{name}{status}",
                    value=f"Key: `{item_key}`\n{desc}" if desc else f"Key: `{item_key}`",
                    inline=True
                )
            
            embed.set_footer(text=f"Use '[p]xpshop use <key>' to change your active background")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error loading owned backgrounds: {e}")
    
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
            name="Available Commands:",
            value="`[p]xpshop backgrounds` - View all backgrounds\n`[p]xpshop buy <key>` - Purchase a background\n`[p]xpshop use <key>` - Set active background\n`[p]xpshop owned` - View your inventory",
            inline=False
        )
        embed.add_field(
            name="Note:",
            value="All users start with the 'default' background. Purchase backgrounds with currency, then use `[p]xpshop use <key>` to activate them!",
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
            user_rank = await self.db.get_user_rank_in_guild(member.id, ctx.guild.id)
            
            # Get user's active background
            active_background = await self.db.get_active_xp_item(member.id, 1)  # 1 = Background
            
            # Generate XP card
            try:
                card_image_bytes = await self.xp_system.card_generator.generate_xp_card(
                    member.id,
                    member.display_name,
                    str(member.avatar.url) if member.avatar else str(member.default_avatar.url),
                    level_stats.level,
                    level_stats.level_xp,
                    level_stats.required_xp,
                    level_stats.total_xp,
                    user_rank,
                    active_background
                )
                
                if card_image_bytes:
                    file = discord.File(card_image_bytes, filename="xp_card.png")
                    await ctx.send(file=file)
                    return
                    
            except Exception as e:
                log.error(f"Error generating XP card for {member.display_name}: {e}")
                # Fall back to embed if card generation fails
            
            # Fallback embed if XP card generation fails
            embed = discord.Embed(
                title=f"{member.display_name}'s Level",
                color=member.color or discord.Color.blue()
            )
            embed.add_field(name="Level", value=level_stats.level, inline=True)
            embed.add_field(name="XP", value=f"{level_stats.level_xp:,}/{level_stats.required_xp:,}", inline=True)
            embed.add_field(name="Total XP", value=f"{level_stats.total_xp:,}", inline=True)
            embed.add_field(name="Rank", value=f"#{user_rank}", inline=True)
            
            # Progress bar
            progress_bar = self.xp_system.get_progress_bar(level_stats.level_xp, level_stats.required_xp)
            embed.add_field(name="Progress", value=f"`{progress_bar}` {level_stats.level_xp/level_stats.required_xp:.1%}", inline=False)
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            embed.set_footer(text=f"Active background: {active_background}")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            log.error(f"Error in level check for {member.display_name}: {e}", exc_info=True)
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
    @commands.cooldown(1, 86400, commands.BucketType.user)  # 24 hours cooldown
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
    
    # Shop commands
    @commands.group(name="shop", aliases=["store"])
    async def shop_group(self, ctx):
        """Shop commands - Buy roles and items with currency"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    
    @shop_group.command(name="list", aliases=["items", "view"])
    async def shop_list(self, ctx):
        """View all available shop items"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            items = await self.shop_system.get_shop_items(ctx.guild.id)
            if not items:
                await ctx.send("🛒 The shop is empty! Admins can add items with `[p]shop add`.")
                return
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title="🛒 Shop Items",
                description="Purchase items with your currency!",
                color=discord.Color.green()
            )
            
            for item in items[:10]:  # Limit to 10 items per page
                item_type = self.shop_system.get_type_name(item['type'])
                emoji = self.shop_system.get_type_emoji(item['type'])
                
                description = f"**{emoji} {item['name']}** - {currency_symbol}{item['price']:,}\n"
                description += f"Type: {item_type}\n"
                
                if item['type'] == self.db.SHOP_TYPE_ROLE and item['role_name']:
                    description += f"Role: {item['role_name']}\n"
                elif item['type'] == self.db.SHOP_TYPE_COMMAND and item['command']:
                    description += f"Command: `{item['command']}`\n"
                
                if item['additional_items']:
                    description += f"Items: {len(item['additional_items'])} additional items\n"
                
                embed.add_field(
                    name=f"#{item['index']} - {item['name']}",
                    value=description,
                    inline=True
                )
            
            embed.set_footer(text=f"Use '[p]shop buy <item_id>' to purchase an item")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving shop items: {e}")
    
    @shop_group.command(name="buy")
    async def shop_buy(self, ctx, item_id: int):
        """Buy a shop item"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            success, message = await self.shop_system.purchase_item(ctx.author, ctx.guild.id, item_id)
            if success:
                currency_symbol = await self.config.currency_symbol()
                embed = discord.Embed(
                    title="✅ Purchase Successful!",
                    description=message,
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="💡 Tip",
                    value="Use `[p]shop list` to see all available items!",
                    inline=False
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"❌ {message}")
                
        except Exception as e:
            await ctx.send(f"❌ Error purchasing item: {e}")
    
    @shop_group.command(name="info")
    async def shop_info(self, ctx, item_id: int):
        """Get detailed information about a shop item"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            item = await self.shop_system.get_shop_item(ctx.guild.id, item_id)
            if not item:
                await ctx.send("❌ Shop item not found.")
                return
            
            currency_symbol = await self.config.currency_symbol()
            item_type = self.shop_system.get_type_name(item['type'])
            emoji = self.shop_system.get_type_emoji(item['type'])
            
            embed = discord.Embed(
                title=f"{emoji} {item['name']}",
                description=f"**Price:** {currency_symbol}{item['price']:,}\n**Type:** {item_type}",
                color=discord.Color.blue()
            )
            
            if item['type'] == self.db.SHOP_TYPE_ROLE:
                if item['role_name']:
                    embed.add_field(name="Role", value=item['role_name'], inline=True)
                if item['role_requirement']:
                    req_role = ctx.guild.get_role(item['role_requirement'])
                    if req_role:
                        embed.add_field(name="Requirement", value=f"Must have {req_role.name}", inline=True)
            
            elif item['type'] == self.db.SHOP_TYPE_COMMAND:
                if item['command']:
                    embed.add_field(name="Command", value=f"`{item['command']}`", inline=True)
            
            if item['additional_items']:
                items_text = "\n".join([f"• {item_text}" for _, item_text in item['additional_items']])
                embed.add_field(name="Additional Items", value=items_text[:1000], inline=False)
            
            embed.set_footer(text=f"Use '[p]shop buy {item_id}' to purchase this item")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving item info: {e}")
    
    # Admin shop commands
    @shop_group.command(name="add")
    @commands.admin_or_permissions(manage_roles=True)
    async def shop_add(self, ctx, item_type: str, price: int, name: str, *, details: str = ""):
        """Add a new shop item (Admin only)
        
        Types: role, command, effect, other
        Usage: [p]shop add role 1000 "VIP Role" @VIPRole
        """
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        try:
            # Parse item type
            type_map = {
                'role': self.db.SHOP_TYPE_ROLE,
                'command': self.db.SHOP_TYPE_COMMAND,
                'effect': self.db.SHOP_TYPE_EFFECT,
                'other': self.db.SHOP_TYPE_OTHER
            }
            
            if item_type.lower() not in type_map:
                await ctx.send("❌ Invalid item type. Use: role, command, effect, or other")
                return
            
            entry_type = type_map[item_type.lower()]
            
            # Get next index
            items = await self.shop_system.get_shop_items(ctx.guild.id)
            next_index = max([item['index'] for item in items], default=0) + 1
            
            role_id = None
            role_name = None
            command = None
            
            if entry_type == self.db.SHOP_TYPE_ROLE:
                # Parse role from details
                if not details:
                    await ctx.send("❌ Please specify a role for role items. Usage: `[p]shop add role 1000 \"VIP Role\" @VIPRole`")
                    return
                
                # Try to find role mention or name
                role = None
                if ctx.message.role_mentions:
                    role = ctx.message.role_mentions[0]
                else:
                    # Try to find by name
                    role = discord.utils.get(ctx.guild.roles, name=details.strip())
                
                if not role:
                    await ctx.send("❌ Role not found. Please mention the role or use the exact name.")
                    return
                
                role_id = role.id
                role_name = role.name
            
            elif entry_type == self.db.SHOP_TYPE_COMMAND:
                command = details.strip()
                if not command:
                    await ctx.send("❌ Please specify a command for command items.")
                    return
            
            # Add shop item
            item_id = await self.shop_system.add_shop_item(
                ctx.guild.id, next_index, price, name, ctx.author.id,
                entry_type, role_name, role_id, None, command
            )
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title="✅ Shop Item Added!",
                description=f"**{name}** - {currency_symbol}{price:,}",
                color=discord.Color.green()
            )
            embed.add_field(name="Type", value=item_type.title(), inline=True)
            embed.add_field(name="ID", value=str(item_id), inline=True)
            embed.add_field(name="Index", value=str(next_index), inline=True)
            
            if role_name:
                embed.add_field(name="Role", value=role_name, inline=True)
            if command:
                embed.add_field(name="Command", value=f"`{command}`", inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error adding shop item: {e}")
    
    @shop_group.command(name="remove", aliases=["delete", "del"])
    @commands.admin_or_permissions(manage_roles=True)
    async def shop_remove(self, ctx, item_id: int):
        """Remove a shop item (Admin only)"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        try:
            # Get item info before deleting
            item = await self.shop_system.get_shop_item(ctx.guild.id, item_id)
            if not item:
                await ctx.send("❌ Shop item not found.")
                return
            
            success = await self.shop_system.delete_shop_item(ctx.guild.id, item_id)
            if success:
                await ctx.send(f"✅ Removed shop item: **{item['name']}**")
            else:
                await ctx.send("❌ Failed to remove shop item.")
                
        except Exception as e:
            await ctx.send(f"❌ Error removing shop item: {e}")
    
    # Waifu commands
    @commands.group(name="waifu", aliases=["wf"])
    async def waifu_group(self, ctx):
        """Waifu system - Claim and manage virtual waifus"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    
    @waifu_group.command(name="claim")
    async def waifu_claim(self, ctx, member: discord.Member, price: int = None):
        """Claim a user as your waifu
        
        Usage: [p]waifu claim @user [price]
        """
        if not await self.config.economy_enabled():
            await ctx.send("❌ Economy system is disabled.")
            return
        
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        if member.bot:
            await ctx.send("❌ You can't claim bots as waifus!")
            return
        
        if member == ctx.author:
            await ctx.send("❌ You can't claim yourself as a waifu!")
            return
        
        try:
            # Check if user is already claimed
            current_owner = await self.db.get_waifu_owner(member.id)
            if current_owner:
                if current_owner == ctx.author.id:
                    await ctx.send("❌ You already own this waifu!")
                    return
                else:
                    await ctx.send("❌ This user is already claimed by someone else!")
                    return
            
            # Set default price if not provided
            if price is None:
                price = await self.db.get_waifu_price(member.id)
            
            # Check if user has enough currency
            user_balance = await self.db.get_user_currency(ctx.author.id)
            if user_balance < price:
                currency_symbol = await self.config.currency_symbol()
                await ctx.send(f"❌ You need {currency_symbol}{price:,} but only have {currency_symbol}{user_balance:,}!")
                return
            
            # Claim the waifu
            success = await self.db.claim_waifu(member.id, ctx.author.id, price)
            if success:
                # Deduct currency
                await self.db.remove_currency(ctx.author.id, price, "waifu_claim", str(member.id), note=f"Claimed {member.display_name}")
                await self.db.log_currency_transaction(ctx.author.id, "waifu_claim", -price, f"Claimed {member.display_name}")
                
                currency_symbol = await self.config.currency_symbol()
                embed = discord.Embed(
                    title="💕 Waifu Claimed!",
                    description=f"You successfully claimed **{member.display_name}** as your waifu!",
                    color=discord.Color.pink()
                )
                embed.add_field(name="Price Paid", value=f"{currency_symbol}{price:,}", inline=True)
                embed.add_field(name="New Owner", value=ctx.author.display_name, inline=True)
                embed.set_thumbnail(url=member.display_avatar.url)
                await ctx.send(embed=embed)
            else:
                await ctx.send("❌ Failed to claim waifu. Please try again.")
                
        except Exception as e:
            await ctx.send(f"❌ Error claiming waifu: {e}")
    
    @waifu_group.command(name="divorce")
    async def waifu_divorce(self, ctx, member: discord.Member):
        """Divorce your waifu
        
        Usage: [p]waifu divorce @user
        """
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            success = await self.db.divorce_waifu(member.id, ctx.author.id)
            if success:
                embed = discord.Embed(
                    title="💔 Waifu Divorced",
                    description=f"You divorced **{member.display_name}**. They are now available for claiming again.",
                    color=discord.Color.red()
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                await ctx.send(embed=embed)
            else:
                await ctx.send("❌ You don't own this waifu or they're not claimed!")
                
        except Exception as e:
            await ctx.send(f"❌ Error divorcing waifu: {e}")
    
    @waifu_group.command(name="info")
    async def waifu_info(self, ctx, member: discord.Member):
        """Get information about a waifu
        
        Usage: [p]waifu info @user
        """
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            waifu_info = await self.db.get_waifu_info(member.id)
            if not waifu_info:
                await ctx.send("❌ This user is not claimed as a waifu.")
                return
            
            waifu_id, claimer_id, price, affinity_id, created_at = waifu_info
            
            # Get owner info
            owner = ctx.guild.get_member(claimer_id) if claimer_id else None
            affinity = ctx.guild.get_member(affinity_id) if affinity_id else None
            
            # Get waifu items
            items = await self.db.get_waifu_items(member.id)
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title=f"💕 {member.display_name}'s Waifu Info",
                color=discord.Color.pink()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            
            if owner:
                embed.add_field(name="Owner", value=owner.display_name, inline=True)
            else:
                embed.add_field(name="Status", value="Unclaimed", inline=True)
            
            embed.add_field(name="Price", value=f"{currency_symbol}{price:,}", inline=True)
            
            if affinity:
                embed.add_field(name="Affinity", value=affinity.display_name, inline=True)
            
            if items:
                items_text = "\n".join([f"{emoji} {name}" for name, emoji in items[:5]])
                if len(items) > 5:
                    items_text += f"\n... and {len(items) - 5} more"
                embed.add_field(name="Items", value=items_text, inline=False)
            
            embed.add_field(name="Claimed", value=f"<t:{int(created_at.timestamp())}:R>", inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error getting waifu info: {e}")
    
    @waifu_group.command(name="list", aliases=["my"])
    async def waifu_list(self, ctx, member: discord.Member = None):
        """List your waifus or someone else's waifus
        
        Usage: [p]waifu list [@user]
        """
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        target = member or ctx.author
        
        try:
            waifus = await self.db.get_user_waifus(target.id)
            if not waifus:
                await ctx.send(f"❌ {target.display_name} doesn't have any waifus.")
                return
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title=f"💕 {target.display_name}'s Waifus",
                color=discord.Color.pink()
            )
            
            for waifu_id, price, affinity_id, created_at in waifus[:10]:  # Limit to 10
                waifu_member = ctx.guild.get_member(waifu_id)
                if waifu_member:
                    affinity = ctx.guild.get_member(affinity_id) if affinity_id else None
                    value = f"Price: {currency_symbol}{price:,}"
                    if affinity:
                        value += f"\nAffinity: {affinity.display_name}"
                    embed.add_field(
                        name=waifu_member.display_name,
                        value=value,
                        inline=True
                    )
            
            if len(waifus) > 10:
                embed.set_footer(text=f"Showing 10 of {len(waifus)} waifus")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error listing waifus: {e}")
    
    @waifu_group.command(name="leaderboard", aliases=["lb", "top"])
    async def waifu_leaderboard(self, ctx):
        """View waifu leaderboard by price
        
        Usage: [p]waifu leaderboard
        """
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            leaderboard = await self.db.get_waifu_leaderboard(10)
            if not leaderboard:
                await ctx.send("❌ No waifus found.")
                return
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title="💕 Waifu Leaderboard",
                description="Most expensive waifus",
                color=discord.Color.pink()
            )
            
            for i, (waifu_id, claimer_id, price) in enumerate(leaderboard, 1):
                waifu_member = ctx.guild.get_member(waifu_id)
                owner = ctx.guild.get_member(claimer_id)
                
                if waifu_member and owner:
                    embed.add_field(
                        name=f"#{i} {waifu_member.display_name}",
                        value=f"Owner: {owner.display_name}\nPrice: {currency_symbol}{price:,}",
                        inline=True
                    )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error getting leaderboard: {e}")
    
    @waifu_group.command(name="price")
    async def waifu_price(self, ctx, member: discord.Member, new_price: int):
        """Set the price for your waifu (Owner only)
        
        Usage: [p]waifu price @user <new_price>
        """
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            # Check if user owns this waifu
            current_owner = await self.db.get_waifu_owner(member.id)
            if current_owner != ctx.author.id:
                await ctx.send("❌ You don't own this waifu!")
                return
            
            await self.db.update_waifu_price(member.id, new_price)
            currency_symbol = await self.config.currency_symbol()
            await ctx.send(f"✅ Set {member.display_name}'s price to {currency_symbol}{new_price:,}")
            
        except Exception as e:
            await ctx.send(f"❌ Error updating waifu price: {e}")
    
    @waifu_group.command(name="affinity")
    async def waifu_affinity(self, ctx, member: discord.Member, affinity_user: discord.Member):
        """Set affinity for your waifu (Owner only)
        
        Usage: [p]waifu affinity @waifu @affinity_user
        """
        if not self._check_systems_ready():
            await ctx.send("❌ Systems are still initializing. Please try again in a moment.")
            return
        
        try:
            # Check if user owns this waifu
            current_owner = await self.db.get_waifu_owner(member.id)
            if current_owner != ctx.author.id:
                await ctx.send("❌ You don't own this waifu!")
                return
            
            await self.db.set_waifu_affinity(member.id, affinity_user.id)
            await ctx.send(f"✅ Set {member.display_name}'s affinity to {affinity_user.display_name}")
            
        except Exception as e:
            await ctx.send(f"❌ Error setting waifu affinity: {e}")
    
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
    @commands.cooldown(1, 5, commands.BucketType.user)  # 5 second cooldown
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
    @commands.cooldown(1, 3, commands.BucketType.user)  # 3 second cooldown
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