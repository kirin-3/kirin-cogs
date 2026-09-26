"""
Nitro Shop System for Unicornia
Handles stock management, purchases, and notifications for Discord Nitro items.
"""

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Literal

import discord
from redbot.core import Config
from redbot.core.utils.chat_formatting import humanize_number

from ..db.economy import DIRECTION_DEBIT, OUTCOME_SETTLED

log = logging.getLogger("red.kirin_cogs.unicornia.nitro")

RECONCILE_SECONDS = 600


class NitroSystem:
    def __init__(self, config: Config, bot, economy_system):
        self.config = config
        self.bot = bot
        self.economy_system = economy_system

        # Hardcoded channel and user IDs as per requirements
        self.ANNOUNCE_CHANNEL_ID = 695155004507422730
        self.ADMIN_NOTIFY_USER_ID = 140186220255903746
        self.PURCHASE_LOG_CHANNEL_ID = 686096388018405408

        # Define defaults if they don't exist in config yet
        # We'll use a specific group for nitro shop
        # nitro_orders: order id -> {user_id, item, price, at}; kept until staff have been notified
        self.config.register_global(
            nitro_stock={"boost": 0, "basic": 0}, nitro_prices={"boost": 250000, "basic": 150000}, nitro_orders={}
        )
        # ponytail: one lock for all purchases; they're rare, and it keeps stock, orders and reconciliation in step
        self._lock = asyncio.Lock()

    async def get_stock(self, item_type: Literal["boost", "basic"]) -> int:
        """Get current stock for an item type"""
        stock = await self.config.nitro_stock()
        return stock.get(item_type, 0)

    async def get_price(self, item_type: Literal["boost", "basic"]) -> int:
        """Get current price for an item type"""
        prices = await self.config.nitro_prices()
        return prices.get(item_type, 0)

    async def set_price(self, item_type: Literal["boost", "basic"], price: int):
        """Set price for an item type"""
        async with self.config.nitro_prices() as prices:
            prices[item_type] = price

    async def set_stock(self, item_type: Literal["boost", "basic"], amount: int) -> int:
        """Set stock to a specific amount and announce the change"""
        old_amount = 0
        async with self.config.nitro_stock() as stock:
            old_amount = stock.get(item_type, 0)
            # Ensure we don't go below 0
            if amount < 0:
                amount = 0
            stock[item_type] = amount

        # Announce only if we are restocking from empty (or negative) to positive
        if old_amount <= 0 and amount > 0:
            await self._announce_stock(item_type, amount)

        return amount

    async def purchase_nitro(self, ctx, item_type: Literal["boost", "basic"]) -> tuple[bool, str]:
        """Process a nitro purchase.

        The stock is reserved and the order recorded before the payment, which uses the order's
        idempotency key, so a crash or a failed notification leaves a record that reconcile() finishes.
        """
        async with self._lock:
            if await self.get_stock(item_type) <= 0:
                return False, "This item is currently out of stock!"

            price = await self.get_price(item_type)
            if price <= 0:
                return False, "This item has no price set."
            wallet, _bank = await self.economy_system.get_balance(ctx.author.id)
            if wallet < price:
                return (
                    False,
                    f"You need {humanize_number(price)} to purchase this item. You only have {humanize_number(wallet)} in your wallet.",
                )

            # Stock first: a crash before the order is written loses a unit of stock, never a paid order
            async with self.config.nitro_stock() as stock:
                stock[item_type] = stock.get(item_type, 0) - 1
            order_id = uuid.uuid4().hex
            async with self.config.nitro_orders() as orders:
                orders[order_id] = {"user_id": ctx.author.id, "item": item_type, "price": price, "at": time.time()}

            outcome = await self.economy_system.db.economy.apply_operation(
                key=self._order_key(order_id),
                user_id=ctx.author.id,
                amount=price,
                direction=DIRECTION_DEBIT,
                source="nitroshop",
                transaction_type="nitro",
                note=f"Nitro Shop: {item_type}",
            )
            if outcome.state != OUTCOME_SETTLED:
                await self._cancel_order(order_id)
                return False, "Transaction failed during currency deduction."

            if not await self._deliver(order_id):
                return True, "Purchase successful! Staff will be notified shortly and will send your code."
        return True, "Purchase successful! An admin has been notified and will send your code shortly."

    @staticmethod
    def _order_key(order_id: str) -> str:
        return f"nitroshop:{order_id}"

    async def _cancel_order(self, order_id: str) -> None:
        """Drop an unpaid order and put its stock back."""
        async with self.config.nitro_orders() as orders:
            order = orders.pop(order_id, None)
        if isinstance(order, dict) and order.get("item") in ("boost", "basic"):
            async with self.config.nitro_stock() as stock:
                stock[order["item"]] = stock.get(order["item"], 0) + 1

    async def _deliver(self, order_id: str) -> bool:
        """Notify staff about a paid order; the order is dropped once someone has been told."""
        order = (await self.config.nitro_orders()).get(order_id)
        if not isinstance(order, dict):
            return True
        if not await self._notify_purchase(order):
            return False
        async with self.config.nitro_orders() as orders:
            orders.pop(order_id, None)
        return True

    async def reconcile(self) -> None:
        """Finish orders a crash or failed notification left behind: notify paid ones, cancel unpaid ones."""
        async with self._lock:
            for order_id in list(await self.config.nitro_orders()):
                if await self.economy_system.db.economy.get_operation(self._order_key(order_id)) is None:
                    log.warning(f"Cancelling unpaid Nitro order {order_id}")
                    await self._cancel_order(order_id)
                elif not await self._deliver(order_id):
                    log.warning(f"Staff still haven't been notified about Nitro order {order_id}")

    async def reconcile_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Nitro order reconciliation failed")
            await asyncio.sleep(RECONCILE_SECONDS)

    async def _announce_stock(self, item_type: str, amount: int):
        """Announce new stock to the public channel"""
        channel = self.bot.get_channel(self.ANNOUNCE_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(self.ANNOUNCE_CHANNEL_ID)
            except discord.HTTPException as e:
                log.warning(f"Could not fetch Nitro Announce Channel {self.ANNOUNCE_CHANNEL_ID}: {e}")
                return

        pretty_name = "Nitro Boost" if item_type == "boost" else "Nitro Basic"

        embed = discord.Embed(
            title="🎉 New Nitro Stock Available!",
            description=f"**{amount}x {pretty_name}** has just been restocked!",
            color=discord.Color(0xFF73FA),
        )
        embed.add_field(name="How to buy?", value="Use the command `[p]nitroshop` to purchase.")

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            log.error(f"Missing permissions to send to Nitro Announce Channel {self.ANNOUNCE_CHANNEL_ID}")

    async def _notify_purchase(self, order: dict) -> bool:
        """Notify admins and log channel about the purchase. Returns whether anyone was notified."""
        user_id, item_type = order.get("user_id"), order.get("item")
        log.info(f"Notifying purchase: {item_type} by {user_id}")
        pretty_name = "Nitro Boost" if item_type == "boost" else "Nitro Basic"

        at = order.get("at")
        embed = discord.Embed(
            title="🔔 New Nitro Purchase",
            color=discord.Color.green(),
            timestamp=datetime.fromtimestamp(at, UTC) if isinstance(at, (int, float)) else discord.utils.utcnow(),
        )
        embed.add_field(name="Buyer", value=f"<@{user_id}> (`{user_id}`)", inline=False)
        embed.add_field(name="Item", value=pretty_name, inline=True)
        embed.add_field(name="Price Paid", value=humanize_number(order.get("price", 0)), inline=True)
        embed.set_footer(text="Please send the code to the user.")

        notified = False

        # 1. Notify Log Channel
        channel = self.bot.get_channel(self.PURCHASE_LOG_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(self.PURCHASE_LOG_CHANNEL_ID)
            except discord.HTTPException as e:
                log.warning(f"Could not fetch Nitro Log Channel {self.PURCHASE_LOG_CHANNEL_ID}: {e}")

        if channel:
            try:
                # Ping the specific user as requested
                await channel.send(content=f"<@{self.ADMIN_NOTIFY_USER_ID}>", embed=embed)
                notified = True
            except discord.Forbidden:
                log.error(f"Missing permissions to send to Nitro Log Channel {self.PURCHASE_LOG_CHANNEL_ID}")
            except Exception as e:
                log.error(f"Failed to send to Nitro Log Channel: {e}")
        else:
            log.warning(f"Nitro Log Channel {self.PURCHASE_LOG_CHANNEL_ID} not found (cache and fetch failed).")

        # 2. Notify Specific Admin via DM (Legacy/Backup)
        try:
            log.info(f"Attempting to notify specific admin {self.ADMIN_NOTIFY_USER_ID}")
            admin = await self.bot.get_or_fetch_user(self.ADMIN_NOTIFY_USER_ID)
            if admin:
                await admin.send(embed=embed)
                notified = True
                log.info(f"Successfully notified specific admin {self.ADMIN_NOTIFY_USER_ID}")
            else:
                log.warning(f"Could not find specific admin user {self.ADMIN_NOTIFY_USER_ID}")
        except discord.HTTPException as e:
            log.error(f"Failed to DM admin {self.ADMIN_NOTIFY_USER_ID}: {e}")
        except Exception as e:
            log.error(f"Unexpected error notifying admin {self.ADMIN_NOTIFY_USER_ID}: {e}")
        return notified
