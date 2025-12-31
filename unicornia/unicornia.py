"""
Unicornia - Full-Featured Leveling and Economy Cog

A Red bot cog that provides complete leveling and economy features similar to Nadeko.
Includes XP gain, currency transactions, gambling, banking, shop, and more.
"""

import functools
import asyncio
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import humanize_number, box

from .database import DatabaseManager
from .systems import (
    XPSystem, EconomySystem, GamblingSystem,
    CurrencyGeneration, CurrencyDecay, ShopSystem,
    ClubSystem, WaifuSystem, NitroSystem
)
from .utils import validate_url, validate_club_name
from .errors import UnicorniaError, SystemNotReadyError
from .commands import (
    ClubCommands, EconomyCommands, GamblingCommands,
    LevelCommands, WaifuCommands, ShopCommands,
    AdminCommands, CurrencyCommands, NitroCommands
)

log = logging.getLogger("red.unicornia")


# See: https://docs.discord-red.com/en/stable/framework_commands.html
class Unicornia(
    ClubCommands, EconomyCommands, GamblingCommands,
    LevelCommands, WaifuCommands, ShopCommands,
    AdminCommands, CurrencyCommands, NitroCommands, commands.Cog
):
    """Full-featured leveling and economy cog with Nadeko-like functionality"""
    
    def __init__(self, bot: Red):
        self.bot = bot
        # See: https://docs.discord-red.com/en/stable/framework_config.html
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        
        # Default configuration
        default_global = {
            "currency_name": "Slut points",
            "currency_symbol": "<:slut:686148402941001730>",
            "xp_enabled": True,
            "economy_enabled": True,
            "gambling_enabled": True,
            "shop_enabled": True,
            "timely_amount": 500,
            "timely_cooldown": 24,  # hours
            "xp_per_message": 3,
            "xp_cooldown": 180,  # seconds
            # Currency generation
            "currency_generation_enabled": True,
            "generation_chance": 0.005,  # 0.5%
            "generation_cooldown": 10,  # seconds
            "generation_min_amount": 60,
            "generation_max_amount": 140,
            "generation_has_password": False,
            "generation_channels": [],  # List of channel IDs (Global)
            # Currency decay
            "decay_percent": 0.01,  # 1% (0 to disable)
            "decay_max_amount": 5000,  # Max amount to decay
            "decay_min_threshold": 15000, # Minimum wealth to trigger decay
            "decay_hour_interval": 48,
            "decay_last_run": 0, # Timestamp of last decay
            # Gambling limits
            "gambling_min_bet": 50,
            "gambling_max_bet": 1000000
        }
        
        default_guild = {
            "excluded_roles": [],
            "xp_included_channels": [],
            "command_whitelist": {}, # {command_name: [channel_ids]}
            "system_whitelist": {}   # {system_name: [channel_ids]}
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
        self.nitro_system = None
    
    async def cog_load(self):
        """Called when the cog is loaded - proper async initialization"""
        try:
            # Initialize database first
            # Look for Nadeko database in the same directory as this cog
            import os
            cog_dir = os.path.dirname(os.path.abspath(__file__))
            nadeko_db_path = os.path.join(cog_dir, "nadeko.db")
            db_path = os.path.join(cog_dir, "data", "unicornia.db")
            self.db = DatabaseManager(db_path, nadeko_db_path)
            await self.db.connect()  # Establish persistent connection
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
            self.club_system = ClubSystem(self.db, self.config, self.bot)
            self.waifu_system = WaifuSystem(self.db, self.config, self.bot)
            self.nitro_system = NitroSystem(self.config, self.bot, self.economy_system)
            
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
            
            if self.db:
                await self.db.close()  # Close persistent connection
                
            log.info("Unicornia: Cog unloaded successfully")
        except Exception as e:
            log.error(f"Unicornia: Error during unload: {e}")
    
    async def red_get_data_for_user(self, *, user_id: int):
        """Get user data for data export/deletion (Red bot requirement)"""
        # See: https://docs.discord-red.com/en/stable/framework_commands.html
        try:
            if not self._check_systems_ready():
                return {}
            
            # Get user's data from all systems
            data = {}
            
            # XP data
            xp_data = await self.db.xp.get_all_user_xp(user_id)
            if xp_data:
                data['xp'] = [{"guild_id": gid, "xp": xp} for gid, xp in xp_data]
            
            # Currency data
            currency = await self.db.economy.get_user_currency(user_id)
            if currency > 0:
                data['currency'] = currency
            
            # Bank data
            bank_data = await self.db.economy.get_bank_user(user_id)
            if bank_data:
                data['bank'] = bank_data
            
            # Waifu data
            waifus = await self.db.waifu.get_user_waifus(user_id)
            if waifus:
                data['waifus'] = waifus
            
            # Transaction history
            transactions = await self.db.economy.get_currency_transactions(user_id, limit=100)
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
    
    # -------------------------------------------------------------------------
    # Public API for other cogs
    # -------------------------------------------------------------------------

    async def get_balance(self, user_id: int) -> Tuple[int, int]:
        """
        Get a user's balance.
        
        Args:
            user_id: The ID of the user.
            
        Returns:
            A tuple of (wallet_balance, bank_balance).
        """
        if not self._check_systems_ready():
            return 0, 0
        return await self.economy_system.get_balance(user_id)

    async def add_balance(self, user_id: int, amount: int, reason: str = "External API", source: str = "external") -> bool:
        """
        Add currency to a user's wallet.
        
        Args:
            user_id: The ID of the user.
            amount: The amount to add.
            reason: The reason for the transaction.
            source: The source of the funds (default: "external").
            
        Returns:
            True if successful, False otherwise.
        """
        if not self._check_systems_ready():
            return False
        # using db layer directly to allow custom transaction type/extra
        return await self.db.economy.add_currency(user_id, amount, "api_add", extra=source, note=reason)

    async def remove_balance(self, user_id: int, amount: int, reason: str = "External API", source: str = "external") -> bool:
        """
        Remove currency from a user's wallet.
        
        Args:
            user_id: The ID of the user.
            amount: The amount to remove.
            reason: The reason for the transaction.
            source: The source of the deduction (default: "external").
            
        Returns:
            True if successful, False if insufficient funds.
        """
        if not self._check_systems_ready():
            return False
        return await self.db.economy.remove_currency(user_id, amount, "api_remove", extra=source, note=reason)

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Global check for all commands in this cog"""
        if not self._check_systems_ready():
            raise SystemNotReadyError()

        # Check whitelists (Skip for bot owner)
        if await self.bot.is_owner(ctx.author):
            return True
            
        if not ctx.guild:
            return True

        # 1. Check Command Whitelist (Specific Rule Overrides General)
        command_whitelist = await self.config.guild(ctx.guild).command_whitelist()
        to_check = ctx.command
        while to_check:
            if to_check.qualified_name in command_whitelist:
                # Rule exists for this command
                if ctx.channel.id in command_whitelist[to_check.qualified_name]:
                    return True # Allowed by specific rule
                else:
                    return False # Blocked (Whitelisted for other channels)
            to_check = to_check.parent

        # 2. Check System Whitelist (General Rule)
        # Determine system from module name (e.g. unicornia.commands.economy -> economy)
        try:
            module_parts = ctx.command.callback.__module__.split('.')
            if 'unicornia' in module_parts and 'commands' in module_parts:
                idx = module_parts.index('commands')
                if idx + 1 < len(module_parts):
                    system_name = module_parts[idx + 1]
                else:
                    system_name = 'core'
            else:
                system_name = 'unknown'
        except Exception:
            system_name = 'unknown'
            
        system_whitelist = await self.config.guild(ctx.guild).system_whitelist()
        if system_name in system_whitelist:
            if ctx.channel.id in system_whitelist[system_name]:
                return True
            else:
                return False # Blocked (Whitelisted for other channels)

        # 3. Default Allow (No rules matched)
        return True

    def _check_systems_ready(self) -> bool:
        """Check if all systems are properly initialized"""
        return all([
            self.db is not None,
            self.xp_system is not None,
            self.economy_system is not None,
            self.gambling_system is not None,
            self.currency_generation is not None,
            self.currency_decay is not None,
            self.nitro_system is not None
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
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        """Global error handler for Unicornia commands"""
        # Only handle errors for commands in this cog
        if ctx.command and ctx.command.cog_name == self.qualified_name:
            
            # Unwrap CommandInvokeError
            if isinstance(error, commands.CommandInvokeError):
                error = error.original
            
            # Handle Custom Errors
            if isinstance(error, UnicorniaError):
                await ctx.send(str(error))
                # Mark as handled to prevent Red's default handler from firing
                ctx.command_failed = False
            elif isinstance(error, commands.UserFeedbackCheckFailure):
                # Let Red handle standard feedback checks (includes our custom ones if we didn't catch them above)
                pass
            elif isinstance(error, commands.CommandInvokeError): # Should be unwrapped already, but just in case
                log.error(f"Error in command '{ctx.command.qualified_name}': {error}", exc_info=error)
    
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
    
