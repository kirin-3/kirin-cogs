"""
Unicornia - Full-Featured Leveling and Economy Cog

A Red bot cog that provides complete leveling and economy features similar to Nadeko.
Includes XP gain, currency transactions, gambling, banking, shop, and more.
"""

import asyncio
import contextlib
import logging
import os
from datetime import datetime
from typing import Any, Literal

from redbot.core import Config, commands
from redbot.core.bot import Red

from .commands import (
    AdminCommands,
    ClubCommands,
    CurrencyCommands,
    EconomyCommands,
    GamblingCommands,
    LevelCommands,
    NitroCommands,
    ShopCommands,
    StockCommands,
    WaifuCommands,
)
from .database import DatabaseManager
from .db.economy import OperationDirection, OperationOutcome
from .errors import SystemNotReadyError, UnicorniaError
from .market_views import StockDashboardView
from .systems import (
    ClubSystem,
    CurrencyDecay,
    CurrencyGeneration,
    EconomySystem,
    GamblingSystem,
    MarketSystem,
    NitroSystem,
    ShopSystem,
    WaifuSystem,
    XPSystem,
    YieldSystem,
)

log = logging.getLogger("red.kirin_cogs.unicornia")


# See: https://docs.discord-red.com/en/stable/framework_commands.html
class Unicornia(
    ClubCommands,
    EconomyCommands,
    GamblingCommands,
    LevelCommands,
    WaifuCommands,
    ShopCommands,
    AdminCommands,
    CurrencyCommands,
    NitroCommands,
    StockCommands,
    commands.Cog,
):
    """
    Full-featured leveling and economy cog with Nadeko-like functionality.

    This system includes:
    - Economy (Wallet/Bank)
    - Leveling (XP/Roles)
    - Gambling (Games)
    - Shop (Items/Roles)
    - Clubs (Groups)
    - Waifus (Collection)
    """

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
            "bank_decay_percent": 0.001,  # 0.1% (0 to disable)
            "decay_max_amount": 5000,  # Max amount to decay
            "decay_min_threshold": 15000,  # Minimum wealth to trigger decay
            "decay_hour_interval": 48,
            "decay_last_run": 0,  # Timestamp of last decay
            # Gambling limits
            "gambling_min_bet": 50,
            "gambling_max_bet": 1000000,
            "reservation_recovery_seconds": 300,
            "dividend_period_hours": 168,
            # Migration
            "nadeko_db_path": None,
        }

        default_guild = {
            "excluded_roles": [],
            "xp_included_channels": [],
            "xp_double_channels": [],
            "command_whitelist": {},  # {command_name: [channel_ids]}
            "system_whitelist": {},  # {system_name: [channel_ids]}
            "market_channel": None,  # Channel ID for Stock Dashboard
            "market_message": None,  # Message ID for Stock Dashboard
        }

        self.config.register_global(**default_global)
        self.config.register_guild(**default_guild)

        # Initialize systems (will be properly initialized in cog_load)
        self.db = None  # type: ignore[assignment]
        self.xp_system = None  # type: ignore[assignment]
        self.economy_system = None  # type: ignore[assignment]
        self.gambling_system = None  # type: ignore[assignment]
        self.currency_generation = None  # type: ignore[assignment]
        self.currency_decay = None  # type: ignore[assignment]
        self.nitro_system = None  # type: ignore[assignment]
        self.market_system = None  # type: ignore[assignment]
        self.yield_system = None  # type: ignore[assignment]
        self.wal_task = None
        self.market_task = None
        self.yield_task = None
        self.reservation_recovery_task = None
        self._whitelist_cache: dict[int, tuple[dict[str, list[int]], dict[str, list[int]]]] = {}

    async def cog_load(self):
        """Called when the cog is loaded - proper async initialization"""
        self._whitelist_cache.clear()
        try:
            # Initialize database first
            cog_dir = os.path.dirname(os.path.abspath(__file__))
            db_path = os.path.join(cog_dir, "data", "unicornia.db")

            nadeko_db_path = await self.config.nadeko_db_path()

            self.db = DatabaseManager(
                db_path,
                nadeko_db_path,
                reconcile_reserved_on_initialize=False,
            )
            await self.db.connect()  # Establish persistent connection
            await self.db.initialize()

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
            self.market_system = MarketSystem(self.db, self.config, self.bot, self.economy_system)
            self.yield_system = YieldSystem(self.db, self.config)
            await self.market_system.initialize()

            raw_recovery_age = await self.config.reservation_recovery_seconds()
            try:
                recovery_age = max(0, int(raw_recovery_age))
            except (TypeError, ValueError):
                recovery_age = 300
                log.warning(
                    "Invalid reservation_recovery_seconds value %r; using %s seconds",
                    raw_recovery_age,
                    recovery_age,
                )
            recovered_count, recovered_total = await self.db.economy.refund_stale_reservations(recovery_age)
            log.info(
                "Orphan reservation startup sweep: %s reservation(s), %s currency refunded",
                recovered_count,
                recovered_total,
            )
            pending_startup_reservations = await self.db.economy.get_stale_reservations(0)
            if pending_startup_reservations:
                self.reservation_recovery_task = asyncio.create_task(
                    self._recover_startup_reservations_after_grace(
                        pending_startup_reservations,
                        recovery_age,
                    )
                )

            # Register Persistent Views
            self.bot.add_view(StockDashboardView(self.market_system))

            # Start background tasks
            await self.currency_decay.start_decay_loop()

            # Start WAL maintenance task
            self.wal_task = asyncio.create_task(self._wal_maintenance_loop())
            self.market_task = asyncio.create_task(self.market_loop())
            self.yield_task = asyncio.create_task(self.yield_loop())

            log.info("Unicornia: All systems initialized successfully")
        except Exception as e:
            log.error(f"Unicornia: Failed to initialize: {e}")
            raise

    async def cog_unload(self):
        """Called when the cog is unloaded - proper cleanup"""
        try:
            if self.wal_task:
                self.wal_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.wal_task

            if self.market_task:
                self.market_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.market_task

            if self.yield_task:
                self.yield_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.yield_task

            if self.reservation_recovery_task:
                self.reservation_recovery_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.reservation_recovery_task

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
                data["xp"] = [{"guild_id": gid, "xp": xp} for gid, xp in xp_data]

            # Currency data
            currency = await self.db.economy.get_user_currency(user_id)
            if currency > 0:
                data["currency"] = currency

            # Bank data
            bank_data = await self.db.economy.get_bank_user(user_id)
            if bank_data:
                data["bank"] = bank_data

            # Waifu data
            waifus = await self.db.waifu.get_user_waifus(user_id)
            if waifus:
                data["waifus"] = waifus

            # Transaction history
            transactions = await self.db.economy.get_currency_transactions(user_id, limit=None)
            if transactions:
                data["transactions"] = transactions

            return data

        except Exception as e:
            log.error(f"Error getting user data for {user_id}: {e}")
            return {}

    async def red_delete_data_for_user(  # type: ignore[override]
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ) -> None:
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

    async def apply_operation(
        self,
        *,
        key: str,
        user_id: int,
        amount: int,
        direction: OperationDirection,
        source: str,
        guild_id: int | None = None,
        reason: str = "",
    ) -> OperationOutcome | None:
        """Apply a balance effect exactly once, keyed by a caller-supplied
        idempotency key.

        Repeating a settled key returns the original result without changing
        the balance or writing another transaction-log row. Other cogs SHOULD
        prefer this over :meth:`add_balance`/:meth:`remove_balance` whenever a
        stable operation identity exists.

        Args:
            key: Unique idempotency key (e.g. "nitro:<guild>:<member>:<ts>").
            user_id: The ID of the user whose wallet is mutated.
            amount: Absolute amount to apply.
            direction: "credit" to add, "debit" to remove.
            source: Calling cog/system identity.
            guild_id: Optional guild context for the operation.
            reason: Human readable reason for the transaction-log row.

        Returns:
            The OperationOutcome, or None if systems are not ready.
        """
        if not self._check_systems_ready():
            return None
        return await self.db.economy.apply_operation(
            key=key,
            user_id=user_id,
            amount=amount,
            direction=direction,
            source=source,
            transaction_type="api_operation",
            guild_id=guild_id,
            extra=source,
            note=reason,
        )

    async def get_balance(self, user_id: int) -> tuple[int, int]:
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

    async def add_balance(
        self, user_id: int, amount: int, reason: str = "External API", source: str = "external"
    ) -> bool:
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
        return await self.economy_system.add_currency(
            user_id, amount, transaction_type="api_add", extra=source, note=reason
        )

    async def remove_balance(
        self, user_id: int, amount: int, reason: str = "External API", source: str = "external"
    ) -> bool:
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
        return await self.economy_system.remove_currency(
            user_id, amount, transaction_type="api_remove", extra=source, note=reason
        )

    async def cog_check(self, ctx: commands.Context) -> bool:  # type: ignore[override]
        """Global check for all commands in this cog"""
        if not self._check_systems_ready():
            raise SystemNotReadyError()

        # Check whitelists (Skip for bot owner)
        if await self.bot.is_owner(ctx.author):
            return True

        if not ctx.guild:
            return True

        # Exception for 'pick' command: Allow if in a generation channel
        # This ensures users can always pick up currency where it spawns,
        # regardless of restrictive system whitelists.
        if ctx.command.name == "pick":
            gen_channels = await self.config.generation_channels()
            if ctx.channel.id in gen_channels:
                return True

        command_whitelist, system_whitelist = await self._get_cached_whitelists(ctx.guild)

        # 1. Check Command Whitelist (Specific Rule Overrides General)
        to_check: Any = ctx.command
        while to_check:
            if to_check.qualified_name in command_whitelist:
                # Rule exists for this command
                return ctx.channel.id in command_whitelist[to_check.qualified_name]
            to_check = to_check.parent

        # 2. Check System Whitelist (General Rule)
        # Determine system from module name (e.g. unicornia.commands.economy -> economy)
        try:
            module_parts = ctx.command.callback.__module__.split(".")
            if "unicornia" in module_parts and "commands" in module_parts:
                idx = module_parts.index("commands")
                if idx + 1 < len(module_parts):
                    system_name = module_parts[idx + 1]
                else:
                    system_name = "core"
            else:
                system_name = "unknown"
        except Exception:
            system_name = "unknown"

        if system_name in system_whitelist:
            return ctx.channel.id in system_whitelist[system_name]

        # 3. Default Allow (No rules matched)
        return True

    @staticmethod
    def _normalize_whitelist(raw: Any) -> dict[str, list[int]]:
        if not isinstance(raw, dict):
            return {}
        normalized: dict[str, list[int]] = {}
        for name, channel_ids in raw.items():
            if not isinstance(name, str) or not isinstance(channel_ids, list):
                continue
            normalized[name] = [channel_id for channel_id in channel_ids if isinstance(channel_id, int)]
        return normalized

    async def _get_cached_whitelists(self, guild) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
        cached = self._whitelist_cache.get(guild.id)
        if cached is not None:
            return cached

        guild_config = self.config.guild(guild)
        command_raw, system_raw = await asyncio.gather(
            guild_config.command_whitelist(), guild_config.system_whitelist()
        )
        cached = (self._normalize_whitelist(command_raw), self._normalize_whitelist(system_raw))
        self._whitelist_cache[guild.id] = cached
        return cached

    def invalidate_whitelist_cache(self, guild_id: int) -> None:
        """Discard one guild's cached command-gate configuration."""
        self._whitelist_cache.pop(guild_id, None)

    def _check_systems_ready(self) -> bool:
        """Check if all systems are properly initialized"""
        return all(
            [
                self.db is not None,
                self.xp_system is not None,
                self.economy_system is not None,
                self.gambling_system is not None,
                self.currency_generation is not None,
                self.currency_decay is not None,
                self.nitro_system is not None,
                self.market_system is not None,
            ]
        )

    async def market_loop(self):
        """Run the market on a restart-safe persisted cadence."""
        await self.bot.wait_until_ready()
        while True:
            try:
                if not self.market_system:
                    await asyncio.sleep(60)
                    continue
                delay = await self.market_system.run_scheduled_tick()
                await asyncio.sleep(max(1.0, delay))
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in market loop: {e}")
                await asyncio.sleep(60)

    async def _recover_startup_reservations_after_grace(
        self,
        reservations: list[dict[str, Any]],
        threshold_seconds: int,
    ) -> None:
        """Recover startup orphans that were initially younger than the grace period."""
        try:
            delay = float(max(0, threshold_seconds))
            try:
                newest_created_at = max(
                    datetime.fromisoformat(str(reservation["created_at"]).replace("Z", "+00:00")).replace(tzinfo=None)
                    for reservation in reservations
                )
                newest_age = max(0.0, (datetime.utcnow() - newest_created_at).total_seconds())
                delay = max(0.0, threshold_seconds - newest_age)
            except (KeyError, TypeError, ValueError):
                # These rows existed before this process started and cannot be
                # live views. A malformed timestamp must not strand them.
                delay = 0.0
            await asyncio.sleep(delay + 1)
            if not self.db:
                return
            count, total = await self.db.economy.refund_reservations(reservations)
            log.info(
                "Deferred startup reservation sweep: %s reservation(s), %s currency refunded",
                count,
                total,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.error("Deferred startup reservation sweep failed: %s", error)

    async def yield_loop(self):
        """Run dividends on their persisted restart-safe cadence."""
        await self.bot.wait_until_ready()
        while True:
            try:
                if not self.yield_system:
                    await asyncio.sleep(60)
                    continue
                delay, outcome = await self.yield_system.run_scheduled_distribution()
                if outcome is not None:
                    log.info(
                        "Dividend period %s: state=%s distributed=%s recipients=%s",
                        outcome.period_end,
                        outcome.state,
                        outcome.distributed,
                        outcome.recipients,
                    )
                await asyncio.sleep(max(1.0, delay))
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Error in dividend loop: %s", e)
                await asyncio.sleep(60)

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
            elif isinstance(error, commands.CommandInvokeError):  # Should be unwrapped already, but just in case
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

        # Process market tracking
        await self.market_system.process_message(message)
