"""
Market System for Unicornia Stock Exchange
"""

import discord
import logging
import asyncio
import math
import random
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple, Union

from ..database import DatabaseManager
from .economy_system import EconomySystem
from ..market_views import StockDashboardView

log = logging.getLogger("red.kirin_cogs.unicornia.market")

class MarketSystem:
    """Core logic for the Stock Market."""

    def __init__(self, db: DatabaseManager, config, bot, economy_system: EconomySystem):
        self.db = db
        self.config = config
        self.bot = bot
        self.economy = economy_system
        
        # State
        self.emoji_buffer = Counter()
        self.stocks_cache: Dict[str, dict] = {} # Symbol -> Stock Dict
        self.emoji_map: Dict[str, str] = {} # Emoji String -> Symbol
        self.regex_pattern: Optional[re.Pattern] = None
        self.market_channel_id: Optional[int] = None
        self.dashboard_message_id: Optional[int] = None
        self.lock = asyncio.Lock()
        self.currency_symbol = ""
        
        # Dashboard Cache
        self.top_expensive: List[dict] = []
        self.top_changed: List[dict] = []
        self.top_held: List[dict] = []

    async def initialize(self):
        """Load stocks into cache and prepare regex."""
        self.currency_symbol = await self.config.currency_symbol()
        stocks = await self.db.stock.get_all_stocks(include_hidden=False)
        self.stocks_cache = {s['symbol']: s for s in stocks}
        self.emoji_map = {s['emoji']: s['symbol'] for s in stocks}
        self._update_regex()
        
        # Initial Dashboard Stats calculation
        await self._update_dashboard_stats()
        
        # Load config
        guild_id = None # Global for now, or per guild?
        # Assuming single guild/global market for simplicity as per "server-wide"
        # Ideally we check config.
        pass

    def _update_regex(self):
        """Compile regex pattern for all tracked emojis."""
        if not self.emoji_map:
            self.regex_pattern = None
            return
            
        # Escape emojis for regex safety
        sorted_emojis = sorted(self.emoji_map.keys(), key=len, reverse=True) # Longest first to avoid partial matches
        pattern_str = '|'.join(re.escape(e) for e in sorted_emojis)
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
                return

            log.info(f"Market Tick: Processing {sum(self.emoji_buffer.values())} emoji interactions.")

            updates = []
            
            # Random Event
            event_multiplier = 1.0
            event_name = None
            if random.random() < 0.05: # 5% chance
                if random.random() < 0.5:
                    event_multiplier = 1.3 # Bull Run
                    event_name = "BULL RUN! 🐂"
                else:
                    event_multiplier = 0.7 # Crash
                    event_name = "MARKET CRASH! 📉"

            for symbol, stock in self.stocks_cache.items():
                usage = self.emoji_buffer[symbol]
                current_price = stock['price']
                volatility = stock['volatility']
                
                # Decay factor to force price down if no usage
                decay = 0.0
                if current_price > 100:
                    decay = 0.001 * volatility # 0.1% decay only if above 100
                
                # Growth factor
                growth = (math.log1p(usage) * 0.05 * volatility)
                
                change_percent = growth - decay
                
                # Add random noise (-2% to +2%)
                noise = random.uniform(-0.02, 0.02)
                
                change_percent += noise
                
                new_price = current_price * (1 + change_percent)
                new_price *= event_multiplier
                
                new_price = max(1, int(new_price)) # Min price 1
                
                updates.append((symbol, new_price, current_price)) # Symbol, New, Old (becomes Previous)
                
                # Update Cache
                stock['price'] = new_price
                stock['previous_price'] = current_price

            # Flush to DB
            await self.db.stock.bulk_update_prices(updates)
            
            # Clear buffer
            self.emoji_buffer.clear()
            
            # Update Stats for Dashboard
            await self._update_dashboard_stats()
        
        # Trigger UI update (outside lock to avoid holding it during slow API calls)
        await self.update_dashboard(event_name)
        log.info(f"Market Tick Completed. Updated {len(updates)} stocks.")

    async def _update_dashboard_stats(self):
        """Calculate and cache leaderboard stats."""
        stocks = list(self.stocks_cache.values())
        if not stocks:
            return

        # 1. Top 10 Most Expensive
        self.top_expensive = sorted(stocks, key=lambda s: s['price'], reverse=True)[:10]
        
        # 2. Top 10 Most Changed (Absolute % change)
        # Avoid division by zero
        def get_change_pct(s):
            prev = s['previous_price']
            if prev <= 0: return 0.0
            return abs((s['price'] - prev) / prev)
            
        self.top_changed = sorted(stocks, key=get_change_pct, reverse=True)[:10]
        
        # 3. Top 10 Most Held
        # Requires DB query
        held_counts = await self.db.stock.get_held_shares_counts() # returns {Symbol: TotalShares}
        
        # Map counts to stock objects (add 'held_shares' key temporarily or just create list)
        top_held_list = []
        for symbol, count in held_counts.items():
            if symbol in self.stocks_cache:
                s = self.stocks_cache[symbol].copy()
                s['held_shares'] = count
                top_held_list.append(s)
        
        self.top_held = sorted(top_held_list, key=lambda s: s['held_shares'], reverse=True)[:10]

    async def update_dashboard(self, event_name: str = None):
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

    async def buy_stock(self, user: discord.Member, symbol: str, amount: int) -> Tuple[bool, str]:
        """Buy stocks."""
        if amount <= 0:
            return False, "Amount must be positive."
        if amount > 100000:
            return False, "Transaction limit exceeded (Max 100,000 shares)."
            
        symbol = symbol.upper()
        
        async with self.lock:
            if symbol not in self.stocks_cache:
                return False, "Stock not found."
            
            stock = self.stocks_cache[symbol]
            current_price = stock['price']

            # Dynamic Costing (Slippage) & Tax
            # Avg Price = (Start + End) / 2
            impact = current_price * amount * 0.0005
            end_price = current_price + impact
            avg_execution_price = (current_price + end_price) / 2
            
            subtotal = avg_execution_price * amount
            tax = subtotal * 0.01
            total_cost = int(subtotal + tax)
            
            # Check Balance
            wallet, bank = await self.economy.get_balance(user.id)
            if wallet < total_cost:
                return False, f"Insufficient funds. You need {total_cost} but have {wallet}."
                
            # Execute Transaction
            # 1. Deduct Money
            if not await self.economy.remove_currency(user.id, total_cost, "stock_buy", f"Bought {amount} {symbol} (Tax: {int(tax)})"):
                return False, "Transaction failed."
                
            # 2. Add Shares & Update Average Cost
            holding = await self.db.stock.get_holding(user.id, symbol)
            current_holding_amt = holding['amount'] if holding else 0
            current_avg = holding['average_cost'] if holding else 0.0
            
            new_total_amt = current_holding_amt + amount
            new_avg_cost = ((current_holding_amt * current_avg) + total_cost) / new_total_amt
            
            await self.db.stock.update_holding(user.id, symbol, amount, new_avg_cost)
            
            # 3. Update DB and Cache with Impact
            await self.db.stock.update_shares_and_price(symbol, amount, impact)
            
            # Update Cache locally
            self.stocks_cache[symbol]['total_shares'] += amount
            self.stocks_cache[symbol]['price'] = max(1, int(end_price))
            
            return True, f"Bought {amount} {symbol} @ ~{int(avg_execution_price)} {self.currency_symbol} (Total: {total_cost:,} {self.currency_symbol} incl. 1% tax)."

    async def sell_stock(self, user: discord.Member, symbol: str, amount: int) -> Tuple[bool, str]:
        """Sell stocks."""
        if amount <= 0:
            return False, "Amount must be positive."
        if amount > 100000:
            return False, "Transaction limit exceeded (Max 100,000 shares)."

        symbol = symbol.upper()
        
        async with self.lock:
            if symbol not in self.stocks_cache:
                return False, "Stock not found."
                
            stock = self.stocks_cache[symbol]
            current_price = stock['price']
            
            # Check Holding
            holding = await self.db.stock.get_holding(user.id, symbol)
            if not holding or holding['amount'] < amount:
                return False, f"You don't have enough shares. Owned: {holding['amount'] if holding else 0}"

            # Dynamic Costing & Tax
            impact = current_price * amount * 0.0005
            end_price = current_price - impact
            avg_execution_price = (current_price + end_price) / 2
            
            subtotal = avg_execution_price * amount
            tax = subtotal * 0.01
            total_payout = int(subtotal - tax)
                
            # Execute Transaction
            # 1. Update Holding
            await self.db.stock.update_holding(user.id, symbol, -amount, cost_basis_update=None) # Cost basis doesn't change on sell
            
            # 2. Add Money
            await self.economy.add_currency(user.id, total_payout, "stock_sell", f"Sold {amount} {symbol} (Tax: {int(tax)})")
            
            # 3. Slippage (Negative impact)
            await self.db.stock.update_shares_and_price(symbol, -amount, -impact)
            
            # Update Cache
            self.stocks_cache[symbol]['total_shares'] -= amount
            self.stocks_cache[symbol]['price'] = max(1, int(end_price))
            
            return True, f"Sold {amount} {symbol} @ ~{int(avg_execution_price)} {self.currency_symbol} (Total: {total_payout:,} {self.currency_symbol} after 1% tax)."

    async def get_portfolio_data(self, user_id: int):
        """Fetch portfolio and transaction history for a user."""
        holdings = await self.db.stock.get_user_holdings(user_id)
        
        # Fetch generic currency transactions
        # Increased limit to ensure we capture stock transactions even if user is active elsewhere
        transactions = await self.economy.get_transaction_history(user_id, limit=1000)
        
        # Parse and group by symbol
        stock_txs = {}
        # Robust Regex to match "Bought 10 LOL" or "Bought 10 LOL @ 50..."
        # Matches: Action (Bought/Sold) | Space | Shares (digits) | Space | Symbol (non-whitespace until @ or end)
        regex = re.compile(r"(Bought|Sold)\s+(\d+)\s+([^\s@]+)", re.IGNORECASE)
        
        for t in transactions:
            # t: (Type, Amount, Reason, DateAdded)
            if len(t) < 4: continue
            t_type, amount, reason, date = t
            
            if t_type in ["stock_buy", "stock_sell"]:
                match = regex.search(reason)
                if match:
                    action, shares, symbol = match.groups()
                    symbol = symbol.upper().strip() # Clean up symbol
                    
                    if symbol not in stock_txs:
                        stock_txs[symbol] = []
                    
                    # Extract price if available (from new format)
                    price_match = re.search(r"@\s+([\d.]+)", reason)
                    price = float(price_match.group(1)) if price_match else 0
                    
                    stock_txs[symbol].append({
                        "action": action,
                        "shares": int(shares),
                        "price": price,
                        "total": abs(amount), # Currency amount is negative for buy, positive for sell
                        "date": date
                    })
        
        return holdings, stock_txs

    async def register_stock(self, symbol: str, name: str, emoji: str, price: int) -> bool:
        """IPO a new stock."""
        success = await self.db.stock.create_stock(symbol, name, emoji, price)
        if success:
            # Refresh cache
            await self.initialize()
        return success
