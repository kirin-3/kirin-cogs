"""
Market System for Unicornia Stock Exchange
"""

import asyncio
import logging
import random
import re
import time
from collections import Counter
from uuid import uuid4

import discord

from ..database import DatabaseManager
from ..market_views import StockDashboardView
from ..stock_market import (
    UnwindOutcome,
    buy_quote,
    fair_values,
    market_price_step,
    maximum_trade_size,
    plan_stock_unwind,
    sell_quote,
    update_smoothed_usage,
)
from .economy_system import EconomySystem

log = logging.getLogger("red.kirin_cogs.unicornia.market")
MARKET_TICK_INTERVAL = 3600


class MarketSystem:
    """Core logic for the Stock Market."""

    def __init__(self, db: DatabaseManager, config, bot, economy_system: EconomySystem):
        self.db = db
        self.config = config
        self.bot = bot
        self.economy = economy_system

        # State
        self.emoji_buffer = Counter()
        self.stocks_cache: dict[str, dict] = {}  # Symbol -> Stock Dict
        self.emoji_map: dict[str, str] = {}  # Emoji String -> Symbol
        self.regex_pattern: re.Pattern | None = None
        self.market_channel_id: int | None = None
        self.dashboard_message_id: int | None = None
        self.lock = asyncio.Lock()
        self.currency_symbol = ""

        # Dashboard Cache
        self.top_expensive: list[dict] = []
        self.top_changed: list[dict] = []
        self.top_held: list[dict] = []

    async def initialize(self):
        """Load stocks into cache and prepare regex."""
        self.currency_symbol = await self.config.currency_symbol()
        stocks = await self.db.stock.get_all_stocks(include_hidden=False)
        self.stocks_cache = {s["symbol"]: s for s in stocks}
        self.emoji_map = {s["emoji"]: s["symbol"] for s in stocks}
        self._update_regex()

        await self.db.stock.backfill_legacy_transactions()

        # Initial Dashboard Stats calculation
        await self._update_dashboard_stats()

        # Load config
        # Assuming single guild/global market for simplicity as per "server-wide"
        # Ideally we check config.
        pass

    def _update_regex(self):
        """Compile regex pattern for all tracked emojis."""
        if not self.emoji_map:
            self.regex_pattern = None
            return

        # Escape emojis for regex safety
        sorted_emojis = sorted(self.emoji_map.keys(), key=len, reverse=True)  # Longest first to avoid partial matches
        pattern_str = "|".join(re.escape(e) for e in sorted_emojis)
        try:
            self.regex_pattern = re.compile(pattern_str)
        except re.error as e:
            log.error(f"Failed to compile market regex: {e}")
            self.regex_pattern = None

    async def process_message(self, message: discord.Message):
        """Track emoji usage."""
        if not self.regex_pattern or message.author.bot:
            return

        # Simple count of occurrences
        # Note: This counts every occurrence. ":joy: :joy:" = 2
        matches = self.regex_pattern.findall(message.content)
        if matches:
            for match in matches:
                symbol = self.emoji_map.get(match)
                if symbol:
                    self.emoji_buffer[symbol] += 1

    async def market_tick(self):
        """Hourly update of stock prices."""
        async with self.lock:
            if not self.stocks_cache:
                await self.set_last_market_tick(int(time.time()))
                return

            log.info(f"Market Tick: Processing {sum(self.emoji_buffer.values())} emoji interactions.")

            updates: list[tuple[str, float, float, float, int]] = []

            # Random Event
            event_multiplier = 1.0
            event_name: str | None = None
            if random.random() < 0.02:
                if random.random() < 0.5:
                    event_multiplier = 1.12
                    event_name = "BULL RUN! 🐂"
                else:
                    event_multiplier = 0.88
                    event_name = "MARKET CRASH! 📉"

            stock_items = list(self.stocks_cache.items())
            smoothed = [
                update_smoothed_usage(float(stock.get("smoothed_usage", 0.0)), self.emoji_buffer[symbol])
                for symbol, stock in stock_items
            ]
            targets = fair_values(smoothed)

            for (symbol, stock), smoothed_usage, target in zip(stock_items, smoothed, targets, strict=True):
                usage = self.emoji_buffer[symbol]
                current_price = float(stock["price"])
                new_price = market_price_step(
                    current_price,
                    target,
                    noise=random.gauss(0.0, 1.0),
                    event_multiplier=event_multiplier,
                )

                updates.append((symbol, new_price, current_price, smoothed_usage, usage))
                log.debug(
                    "Market tick %s: usage=%s smoothed=%.3f fair=%.3f price=%.3f",
                    symbol,
                    usage,
                    smoothed_usage,
                    target,
                    new_price,
                )

            # Commit the economic state and completion timestamp atomically.
            # Cache and usage remain untouched if persistence fails.
            completed_at = int(time.time())
            await self.db.stock.bulk_update_prices(updates, completed_at=completed_at)

            for symbol, new_price, current_price, smoothed_usage, usage in updates:
                stock = self.stocks_cache[symbol]
                stock["price"] = new_price
                stock["previous_price"] = current_price
                stock["smoothed_usage"] = smoothed_usage
                stock["period_usage"] = int(stock.get("period_usage", 0)) + usage

            # Clear buffer
            self.emoji_buffer.clear()

            # Update Stats for Dashboard
            await self._update_dashboard_stats()

        # Trigger UI update (outside lock to avoid holding it during slow API calls)
        await self.update_dashboard(event_name)
        log.info(f"Market Tick Completed. Updated {len(updates)} stocks.")

    async def get_last_market_tick(self) -> int | None:
        """Return the last completed market tick, or ``None`` on first run."""
        async with self.db._get_connection() as db:
            row = await (await db.execute("SELECT Value FROM BotConfig WHERE Key = 'LastMarketTick'")).fetchone()
        if not row or row[0] in (None, ""):
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return None

    async def set_last_market_tick(self, timestamp: int) -> None:
        """Persist the completion timestamp for a successful market tick."""
        async with self.db._get_connection() as db:
            await db.execute(
                """
                INSERT INTO BotConfig (Key, Value, Description)
                VALUES ('LastMarketTick', ?, 'Timestamp of last completed market tick')
                ON CONFLICT(Key) DO UPDATE SET Value = excluded.Value
                """,
                (str(timestamp),),
            )
            await db.commit()

    async def run_scheduled_tick(self, now: int | None = None) -> float:
        """Run one due/catch-up tick and return seconds until the next check."""
        current_time = int(time.time()) if now is None else now
        last_tick = await self.get_last_market_tick()
        if last_tick is None:
            await self.set_last_market_tick(current_time)
            return float(MARKET_TICK_INTERVAL)

        remaining = last_tick + MARKET_TICK_INTERVAL - current_time
        if remaining > 0:
            return float(remaining)

        await self.market_tick()
        return float(MARKET_TICK_INTERVAL)

    async def _update_dashboard_stats(self):
        """Calculate and cache leaderboard stats."""
        stocks = list(self.stocks_cache.values())
        if not stocks:
            return

        # 1. Top 10 Most Expensive
        self.top_expensive = sorted(stocks, key=lambda s: s["price"], reverse=True)[:10]

        # 2. Top 10 Most Changed (Absolute % change)
        # Avoid division by zero
        def get_change_pct(s):
            prev = s["previous_price"]
            if prev <= 0:
                return 0.0
            return abs((s["price"] - prev) / prev)

        self.top_changed = sorted(stocks, key=get_change_pct, reverse=True)[:10]

        # 3. Top 10 Most Held
        # Requires DB query
        held_counts = await self.db.stock.get_held_shares_counts()  # returns {Symbol: TotalShares}

        # Map counts to stock objects (add 'held_shares' key temporarily or just create list)
        top_held_list = []
        for symbol, count in held_counts.items():
            if symbol in self.stocks_cache:
                s = self.stocks_cache[symbol].copy()
                s["held_shares"] = count
                top_held_list.append(s)

        self.top_held = sorted(top_held_list, key=lambda s: s["held_shares"], reverse=True)[:10]

    async def update_dashboard(self, event_name: str | None = None):
        """Update the dashboard message in all configured guilds."""
        for guild in self.bot.guilds:
            channel_id = await self.config.guild(guild).market_channel()
            message_id = await self.config.guild(guild).market_message()

            if not channel_id or not message_id:
                continue

            channel = guild.get_channel(channel_id)
            if not channel:
                continue

            try:
                message = await channel.fetch_message(message_id)
            except (discord.NotFound, discord.Forbidden):
                # Auto-cleanup if message/channel is gone
                await self.config.guild(guild).market_channel.clear()
                await self.config.guild(guild).market_message.clear()
                log.info(f"Dashboard message not found in {guild.name}, clearing config.")
                continue

            # Rebuild V2 Dashboard
            try:
                # Update using the View which handles layout internally
                # The view's __init__ triggers update_components()
                view = StockDashboardView(self, event_name)

                # IMPORTANT: When editing to V2, we must clear embeds if we used them before,
                # but discord.py V2 handles message structure.
                # If we send a V2 view, we shouldn't send an embed.
                await message.edit(embed=None, view=view)
            except Exception as e:
                log.error(f"Failed to update dashboard in {guild.name}: {e}")

    async def buy_stock(self, user: discord.Member, symbol: str, amount: int) -> tuple[bool, str]:
        """Buy stocks."""
        if amount <= 0:
            return False, "Amount must be positive."

        symbol = symbol.upper()

        async with self.lock:
            if symbol not in self.stocks_cache:
                return False, "Stock not found."

            stock = self.stocks_cache[symbol]
            current_price = float(stock["price"])
            reserve = float(stock["share_reserve"])
            maximum = maximum_trade_size(reserve, "buy")
            if amount > maximum:
                return False, f"Trade impact limit exceeded. Maximum buy: {maximum:,} shares."
            quote = buy_quote(current_price, reserve, amount)

            subtotal = quote.average_execution_price * amount
            tax = subtotal * 0.01
            total_cost = int(subtotal + tax)

            executed = await self.db.stock.execute_buy(
                user_id=user.id,
                symbol=symbol,
                shares=amount,
                exec_price=quote.average_execution_price,
                tax=int(tax),
                total_cost=total_cost,
                spot_after=quote.spot_after,
                reserve_after=quote.reserve_after,
            )
            if not executed:
                wallet = await self.db.economy.get_user_currency(user.id)
                return False, f"Insufficient funds. You need {total_cost} but have {wallet}."

            # Update Cache locally
            self.stocks_cache[symbol]["total_shares"] += amount
            self.stocks_cache[symbol]["price"] = quote.spot_after
            self.stocks_cache[symbol]["share_reserve"] = quote.reserve_after

            return (
                True,
                f"Bought {amount} {symbol} @ ~{quote.average_execution_price:,.2f} {self.currency_symbol} (Total: {total_cost:,} {self.currency_symbol} incl. 1% tax).",
            )

    async def sell_stock(self, user: discord.Member, symbol: str, amount: int) -> tuple[bool, str]:
        """Sell stocks."""
        if amount <= 0:
            return False, "Amount must be positive."

        symbol = symbol.upper()

        async with self.lock:
            if symbol not in self.stocks_cache:
                return False, "Stock not found."

            stock = self.stocks_cache[symbol]
            current_price = float(stock["price"])
            reserve = float(stock["share_reserve"])

            # Check Holding
            holding = await self.db.stock.get_holding(user.id, symbol)
            if not holding or holding["amount"] < amount:
                return False, f"You don't have enough shares. Owned: {holding['amount'] if holding else 0}"

            maximum = maximum_trade_size(reserve, "sell")
            if amount > maximum:
                return False, f"Trade impact limit exceeded. Maximum sell: {maximum:,} shares."
            quote = sell_quote(current_price, reserve, amount)

            subtotal = quote.average_execution_price * amount
            tax = subtotal * 0.01
            total_payout = int(subtotal - tax)

            executed = await self.db.stock.execute_sell(
                user_id=user.id,
                symbol=symbol,
                shares=amount,
                exec_price=quote.average_execution_price,
                tax=int(tax),
                total_payout=total_payout,
                spot_after=quote.spot_after,
                reserve_after=quote.reserve_after,
            )
            if not executed:
                return False, "Transaction failed because the holding changed."

            # Update Cache
            self.stocks_cache[symbol]["total_shares"] -= amount
            self.stocks_cache[symbol]["price"] = quote.spot_after
            self.stocks_cache[symbol]["share_reserve"] = quote.reserve_after

            return (
                True,
                f"Sold {amount} {symbol} @ ~{quote.average_execution_price:,.2f} {self.currency_symbol} (Total: {total_payout:,} {self.currency_symbol} after 1% tax).",
            )

    async def plan_unwind(self):
        """Read and plan every current holding without mutating market state."""
        holdings, ledger = await self.db.stock.get_unwind_records()
        return plan_stock_unwind(holdings, ledger)

    async def unwind_market(self, *, confirm: bool = False) -> UnwindOutcome:
        """Dry-run or execute the owner-triggered, resumable market unwind."""
        should_update_dashboard = False
        async with self.lock:
            plan = await self.plan_unwind()
            if not confirm:
                return UnwindOutcome(plan=plan)
            if plan.unresolvable:
                return UnwindOutcome(plan=plan, aborted=True)

            run_id = await self.db.stock.get_unwind_run_id()
            if not plan.refunds and run_id is None:
                return UnwindOutcome(plan=plan)
            if run_id is None:
                run_id = uuid4().hex
                await self.db.stock.set_unwind_run_id(run_id)

            for item in plan.refunds:
                await self.db.economy.apply_operation(
                    key=f"stock_unwind:{run_id}:{item.user_id}:{item.symbol}",
                    user_id=item.user_id,
                    amount=item.refund,
                    direction="credit",
                    source="stock_market",
                    transaction_type="stock_unwind",
                    extra=item.symbol,
                    note=f"Refunded {item.shares} {item.symbol} at recorded cost basis",
                    result={"symbol": item.symbol, "shares": item.shares, "refund": item.refund},
                )
                closed = await self.db.stock.close_unwound_holding(
                    user_id=item.user_id,
                    symbol=item.symbol,
                    shares=item.shares,
                    per_share_cost=item.per_share_cost,
                    refund=item.refund,
                )
                if not closed:
                    raise RuntimeError(f"Holding changed during unwind: {item.user_id}/{item.symbol}")

            # A resumed run may have closed its final holding before it was
            # interrupted. Repeating finalization is safe and ensures that a
            # persisted run identifier can never strand the market half-reset.
            await self.db.stock.reset_market()
            stocks = await self.db.stock.get_all_stocks(include_hidden=False)
            self.stocks_cache = {stock["symbol"]: stock for stock in stocks}
            await self._update_dashboard_stats()
            await self.db.stock.clear_unwind_run_id()
            should_update_dashboard = True

        if should_update_dashboard:
            await self.update_dashboard()
        return UnwindOutcome(plan=plan, executed=True, run_id=run_id)

    async def get_portfolio_data(self, user_id: int):
        """Fetch portfolio and transaction history for a user."""
        holdings = await self.db.stock.get_user_holdings(user_id)

        stock_txs: dict[str, list[dict]] = {}
        for transaction in await self.db.stock.get_transactions(user_id):
            if transaction.get("kind") != "trade":
                continue
            stock_txs.setdefault(transaction["symbol"], []).append(transaction)

        return holdings, stock_txs

    async def register_stock(self, symbol: str, name: str, emoji: str, price: int) -> bool:
        """IPO a new stock."""
        success = await self.db.stock.create_stock(symbol, name, emoji, price)
        if success:
            # Refresh cache
            await self.initialize()
        return success
