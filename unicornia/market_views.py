"""
Market UI Components for Unicornia Stock Exchange
"""

import discord
from discord import ui
from redbot.core.utils.chat_formatting import humanize_number

# --- Step 3: Final Transaction Modal (Amount Only) ---
class StockAmountModal(ui.Modal):
    def __init__(self, market_system, transaction_type: str, symbol: str):
        super().__init__(title=f"{transaction_type.title()} {symbol}")
        self.market_system = market_system
        self.transaction_type = transaction_type # "buy" or "sell"
        self.symbol = symbol
        
        self.amount_input = ui.TextInput(
            label="Amount (Shares)",
            placeholder="Enter number of shares",
            min_length=1,
            max_length=10,
            style=discord.TextStyle.short
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        amount_str = self.amount_input.value.strip().lower()
        
        # Handle 'all' for selling
        if self.transaction_type == "sell" and amount_str == "all":
            holding = await self.market_system.db.stock.get_holding(interaction.user.id, self.symbol)
            if not holding:
                await interaction.response.send_message("❌ Error finding holding.", ephemeral=True)
                return
            amount = holding['amount']
        elif not amount_str.isdigit():
             await interaction.response.send_message("❌ Amount must be a positive number.", ephemeral=True)
             return
        else:
            amount = int(amount_str)
            
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
            return

        # Execute Transaction
        if self.transaction_type == "buy":
            success, msg = await self.market_system.buy_stock(interaction.user, self.symbol, amount)
        else:
            success, msg = await self.market_system.sell_stock(interaction.user, self.symbol, amount)
            
        if success:
            await interaction.response.send_message(f"<a:zz_YesTick:729318762356015124> {msg}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

class StockQuickBuyModal(ui.Modal):
    """Modal for quickly buying a stock by symbol."""
    def __init__(self, market_system):
        super().__init__(title="Quick Buy Stock")
        self.market_system = market_system
        
        self.symbol_input = ui.TextInput(
            label="Stock Symbol",
            placeholder="e.g. UNICORN",
            min_length=1,
            max_length=10,
            style=discord.TextStyle.short
        )
        self.amount_input = ui.TextInput(
            label="Amount (Shares)",
            placeholder="Enter number of shares",
            min_length=1,
            max_length=10,
            style=discord.TextStyle.short
        )
        self.add_item(self.symbol_input)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        symbol = self.symbol_input.value.strip().upper()
        amount_str = self.amount_input.value.strip()
        
        if symbol not in self.market_system.stocks_cache:
             await interaction.response.send_message(f"❌ Stock symbol `{symbol}` not found.", ephemeral=True)
             return

        if not amount_str.isdigit():
             await interaction.response.send_message("❌ Amount must be a positive number.", ephemeral=True)
             return
             
        amount = int(amount_str)
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
            return

        success, msg = await self.market_system.buy_stock(interaction.user, symbol, amount)
        if success:
            await interaction.response.send_message(f"<a:zz_YesTick:729318762356015124> {msg}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

# --- Step 2: Selection Views (Ephemeral) with Pagination ---

class StockBuySelectView(ui.View):
    def __init__(self, market_system, all_stocks: list):
        super().__init__(timeout=60)
        self.market_system = market_system
        self.all_stocks = all_stocks # Full list of stock dicts
        self.current_page = 0
        self.items_per_page = 25
        
        self.select = None
        self.update_components()

    def update_components(self):
        self.clear_items()
        
        # Calculate pagination
        total_pages = max(1, (len(self.all_stocks) - 1) // self.items_per_page + 1)
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_stocks = self.all_stocks[start:end]
        
        # Create Select Options
        options = []
        for s in page_stocks:
            options.append(discord.SelectOption(
                label=f"{s['symbol']} - {s['price']:,}",
                value=s['symbol'],
                emoji=s['emoji'],
                description=s['name'][:100]
            ))
            
        if not options:
            options.append(discord.SelectOption(label="No stocks available", value="NONE"))

        # Select Menu
        self.select = ui.Select(
            placeholder=f"Select a stock to buy (Page {self.current_page + 1}/{total_pages})...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=(not page_stocks)
        )
        self.select.callback = self.on_select
        self.add_item(self.select)
        
        # Pagination Buttons (Only if needed)
        if total_pages > 1:
            prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
            next_btn = ui.Button(label="▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= total_pages - 1))
            
            prev_btn.callback = self.prev_page
            next_btn.callback = self.next_page
            
            self.add_item(prev_btn)
            self.add_item(next_btn)

    async def on_select(self, interaction: discord.Interaction):
        symbol = self.select.values[0]
        if symbol == "NONE": return
        await interaction.response.send_modal(StockAmountModal(self.market_system, "buy", symbol))

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        total_pages = (len(self.all_stocks) - 1) // self.items_per_page + 1
        self.current_page = min(total_pages - 1, self.current_page + 1)
        self.update_components()
        await interaction.response.edit_message(view=self)

class StockSellSelectView(ui.View):
    def __init__(self, market_system, user_holdings: list):
        super().__init__(timeout=60)
        self.market_system = market_system
        self.user_holdings = user_holdings
        self.current_page = 0
        self.items_per_page = 25
        
        self.select = None
        self.update_components()

    def update_components(self):
        self.clear_items()
        
        total_pages = max(1, (len(self.user_holdings) - 1) // self.items_per_page + 1)
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_holdings = self.user_holdings[start:end]
        
        options = []
        for h in page_holdings:
            options.append(discord.SelectOption(
                label=f"{h['symbol']} (Owned: {h['amount']:,})",
                value=h['symbol'],
                emoji=h['emoji'],
                description=f"Current Price: {h['current_price']:,}"
            ))
            
        if not options:
            options.append(discord.SelectOption(label="No stocks to sell", value="NONE"))

        self.select = ui.Select(
            placeholder=f"Select a stock to sell (Page {self.current_page + 1}/{total_pages})...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=(not page_holdings)
        )
        self.select.callback = self.on_select
        self.add_item(self.select)
        
        if total_pages > 1:
            prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
            next_btn = ui.Button(label="▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= total_pages - 1))
            
            prev_btn.callback = self.prev_page
            next_btn.callback = self.next_page
            
            self.add_item(prev_btn)
            self.add_item(next_btn)

    async def on_select(self, interaction: discord.Interaction):
        symbol = self.select.values[0]
        if symbol == "NONE": return
        await interaction.response.send_modal(StockAmountModal(self.market_system, "sell", symbol))

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        total_pages = (len(self.user_holdings) - 1) // self.items_per_page + 1
        self.current_page = min(total_pages - 1, self.current_page + 1)
        self.update_components()
        await interaction.response.edit_message(view=self)

# --- Step 4: Portfolio View (V2) ---

class StockPortfolioView(ui.LayoutView):
    """V2 Paginated Portfolio View with Transaction History."""
    def __init__(self, market_system, user_id: int, holdings: list, transactions: dict):
        super().__init__(timeout=180)
        self.market_system = market_system
        self.user_id = user_id
        # Sort by Value Descending
        self.holdings = sorted(holdings, key=lambda h: h['amount'] * h['current_price'], reverse=True)
        self.transactions = transactions
        self.current_page = 0
        self.items_per_page = 5
        self.update_components()

    def update_components(self):
        self.clear_items()
        container = ui.Container(accent_color=discord.Color.blue())
        
        if not self.holdings:
            container.add_item(ui.TextDisplay(content="## 📉 My Portfolio\nYou don't own any stocks."))
            self.add_item(container)
            return

        total_value = sum(h['amount'] * h['current_price'] for h in self.holdings)
        total_cost = sum(h['amount'] * h['average_cost'] for h in self.holdings)
        total_profit = total_value - total_cost
        total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0
        currency = self.market_system.currency_symbol
        
        # Header
        header_text = f"## 📈 Portfolio Overview\n"
        header_text += f"**Total Value**: {total_value:,.0f} {currency}\n"
        header_text += f"**Total Profit**: {total_profit:,.0f} {currency} ({total_profit_pct:+.1f}%)"
        container.add_item(ui.TextDisplay(content=header_text))
        container.add_item(ui.Separator())
        
        # Pagination
        total_pages = max(1, (len(self.holdings) - 1) // self.items_per_page + 1)
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_holdings = self.holdings[start:end]
        
        container.add_item(ui.TextDisplay(content=f"### Holdings (Page {self.current_page + 1}/{total_pages})"))
        
        for h in page_holdings:
            symbol = h['symbol']
            amount = h['amount']
            avg_cost = h['average_cost']
            current_price = h['current_price']
            emoji = h['emoji']
            
            value = amount * current_price
            cost = amount * avg_cost
            profit = value - cost
            profit_pct = (profit / cost * 100) if cost > 0 else 0
            arrow = "🟢" if profit >= 0 else "🔴"
            
            stock_info = f"{emoji} **{symbol}**: {amount:,} shares\n"
            stock_info += f"Value: {value:,.0f} {currency} | Avg: {avg_cost:,.1f} {currency} | {arrow} P/L: {profit:,.0f} {currency} ({profit_pct:+.1f}%)"
            
            # History
            txs = self.transactions.get(symbol, [])
            if txs:
                stock_info += "\n*Last 5 Transactions:*\n"
                recent_txs = txs[:5]
                for t in recent_txs:
                    action_emoji = "Buy" if "bought" in t['action'].lower() else "Sell"
                    price_display = f"{t['price']:,}" if t['price'] > 0 else "?"
                    stock_info += f"- {action_emoji} {t['shares']} @ {price_display} {currency}\n"
            
            container.add_item(ui.TextDisplay(content=stock_info))
            container.add_item(ui.Separator())
            
        # Buttons
        if total_pages > 1:
            prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
            next_btn = ui.Button(label="▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= total_pages - 1))
            
            prev_btn.callback = self.prev_page
            next_btn.callback = self.next_page
            
            container.add_item(ui.ActionRow(prev_btn, next_btn))
            
        self.add_item(container)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        total_pages = (len(self.holdings) - 1) // self.items_per_page + 1
        self.current_page = min(total_pages - 1, self.current_page + 1)
        self.update_components()
        await interaction.response.edit_message(view=self)

# --- Step 3: Show All Stocks View (V2) ---

class StockListView(ui.LayoutView):
    """Ephemeral V2 View to show all stocks (Paginated)."""
    def __init__(self, market_system, held_counts: dict = None):
        super().__init__(timeout=180)
        self.market_system = market_system
        self.held_counts = held_counts or {}
        
        # Prepare stocks list with held data
        stocks_list = []
        for s in self.market_system.stocks_cache.values():
            s_copy = s.copy()
            s_copy['held_shares'] = self.held_counts.get(s['symbol'], 0)
            stocks_list.append(s_copy)
            
        # Sort by Price Descending
        self.all_stocks = sorted(stocks_list, key=lambda s: s['price'], reverse=True)
        self.current_page = 0
        self.items_per_page = 30
        self.update_components()

    def update_components(self):
        self.clear_items()
        container = ui.Container(accent_color=discord.Color.gold())
        
        # Pagination Logic
        total_pages = max(1, (len(self.all_stocks) - 1) // self.items_per_page + 1)
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_stocks = self.all_stocks[start:end]
        
        container.add_item(ui.TextDisplay(content=f"## 📋 All Stocks (Live Prices) - Page {self.current_page + 1}/{total_pages}"))
        container.add_item(ui.Separator())

        current_text = ""
        for s in page_stocks:
            price = s['price']
            prev = s['previous_price']
            change = price - prev
            change_pct = (change / prev * 100) if prev > 0 else 0
            arrow = "🟢" if change >= 0 else "🔴"
            held = s.get('held_shares', 0)
            
            # Format: Emoji Ticker: Price (Change) | Circ: Amount
            line = f"{s['emoji']} **{s['symbol']}**: {price:,} {self.market_system.currency_symbol} {arrow} ({change_pct:+.1f}%) | Circ: {held:,}\n"
            current_text += line
            
        if not current_text:
            current_text = "No stocks found."
            
        container.add_item(ui.TextDisplay(content=current_text))
        
        # Pagination Buttons
        if total_pages > 1:
            prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
            next_btn = ui.Button(label="▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= total_pages - 1))
            
            prev_btn.callback = self.prev_page
            next_btn.callback = self.next_page
            
            container.add_item(ui.ActionRow(prev_btn, next_btn))
            
        self.add_item(container)
        
    async def prev_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        total_pages = (len(self.all_stocks) - 1) // self.items_per_page + 1
        self.current_page = min(total_pages - 1, self.current_page + 1)
        self.update_components()
        await interaction.response.edit_message(view=self)

# --- Step 1: Main Dashboard ---

class StockDashboardView(ui.LayoutView):
    """Components V2 Dashboard for Unicornia Stock Exchange."""
    
    def __init__(self, market_system, event_name: str = None):
        super().__init__(timeout=None) # Persistent view
        self.market_system = market_system
        self.event_name = event_name
        self.update_components()

    def update_components(self):
        self.clear_items()
        
        # Main Container
        container = ui.Container(accent_color=discord.Color.purple())
        
        # Header
        container.add_item(ui.TextDisplay(content="## 🏙️ Unicornia Stock Exchange\nWelcome to the Market! Use the buttons below to trade.\nPrices update hourly. More info about the stock system can be found [here.](https://canary.discord.com/channels/684360255798509578/1456926874050625638/1456926874050625638)"))
        container.add_item(ui.Separator())
        
        # Event News
        if self.event_name:
            container.add_item(ui.TextDisplay(content=f"### 📢 MARKET NEWS\n**{self.event_name}**"))
            container.add_item(ui.Separator())
            
        # Helper for generating list text
        def generate_list_text(stocks_list, metric_func):
            text = ""
            for s in stocks_list:
                price = s['price']
                prev = s['previous_price']
                change = price - prev
                change_pct = (change / prev * 100) if prev > 0 else 0
                arrow = "🟢" if change >= 0 else "🔴"
                
                # Format: Emoji Symbol: Price Arrow (Change%) | Metric
                extra_info = metric_func(s)
                line = f"{s['emoji']} **{s['symbol']}**: {price:,} {self.market_system.currency_symbol} {arrow} ({change_pct:+.1f}%) {extra_info}\n"
                text += line
            return text if text else "None"

        # 1. Top 10 Most Expensive
        if self.market_system.top_expensive:
            expensive_text = generate_list_text(
                self.market_system.top_expensive,
                lambda s: ""
            )
            container.add_item(ui.TextDisplay(content=f"### 💎 Top 10 Most Expensive\n{expensive_text}"))
            container.add_item(ui.Separator())

        # 2. Top 10 Most Changed (Last Hour)
        if self.market_system.top_changed:
            changed_text = generate_list_text(
                self.market_system.top_changed,
                lambda s: ""
            )
            container.add_item(ui.TextDisplay(content=f"### ⚡ Top 10 Movers (1h)\n{changed_text}"))
            container.add_item(ui.Separator())

        # 3. Top 10 In Circulation (Held)
        if self.market_system.top_held:
            held_text = generate_list_text(
                self.market_system.top_held,
                lambda s: f"| 👥 Circ: {s.get('held_shares', 0):,}"
            )
            container.add_item(ui.TextDisplay(content=f"### 🐋 In Circulation (Top 10)\n{held_text}"))
        else:
            container.add_item(ui.TextDisplay(content="### 📊 Market Status\nMarket is initializing or empty."))
            
        # Footer-ish
        container.add_item(ui.Separator())
        # Use Discord Timestamp <t:TIMESTAMP:R> for relative time
        ts = int(discord.utils.utcnow().timestamp())
        container.add_item(ui.TextDisplay(content=f"*Last Update: <t:{ts}:R>*"))
        
        # Interactive Controls (Must be wrapped in ActionRow)
        
        # Row 1: Quick Buy | Browse | Sell
        quick_buy_btn = ui.Button(label="Quick Buy", style=discord.ButtonStyle.success, custom_id="market:quick_buy", row=0)
        browse_btn = ui.Button(label="Browse Market", style=discord.ButtonStyle.primary, custom_id="market:browse", row=0)
        sell_btn = ui.Button(label="Sell Stock", style=discord.ButtonStyle.danger, custom_id="market:sell", row=0)
        
        quick_buy_btn.callback = self.quick_buy_button
        browse_btn.callback = self.browse_button
        sell_btn.callback = self.sell_button

        # Row 2: Portfolio | Show All
        portfolio_btn = ui.Button(label="My Portfolio", style=discord.ButtonStyle.secondary, custom_id="market:portfolio", row=1)
        show_all_btn = ui.Button(label="Show All Stocks", style=discord.ButtonStyle.secondary, custom_id="market:show_all", row=1)
        
        portfolio_btn.callback = self.portfolio_button
        show_all_btn.callback = self.refresh_button
        
        container.add_item(ui.ActionRow(quick_buy_btn, browse_btn, sell_btn))
        container.add_item(ui.ActionRow(portfolio_btn, show_all_btn))
        
        self.add_item(container)

    async def quick_buy_button(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StockQuickBuyModal(self.market_system))

    async def browse_button(self, interaction: discord.Interaction):
        # Prepare stock options (Sorted Alphabetically by Symbol)
        stocks = sorted(self.market_system.stocks_cache.values(), key=lambda s: s['symbol'])
        if not stocks:
            await interaction.response.send_message("Market is empty.", ephemeral=True)
            return
            
        # Send Ephemeral View for Selection
        await interaction.response.send_message(
            "Browse stocks to buy:",
            view=StockBuySelectView(self.market_system, stocks),
            ephemeral=True
        )

    async def sell_button(self, interaction: discord.Interaction):
        # Fetch holdings first
        holdings = await self.market_system.db.stock.get_user_holdings(interaction.user.id)
        if not holdings:
            await interaction.response.send_message("You don't own any stocks to sell.", ephemeral=True)
            return
            
        # Send Ephemeral View for Selection
        await interaction.response.send_message(
            "Select a stock to sell:", 
            view=StockSellSelectView(self.market_system, holdings), 
            ephemeral=True
        )

    async def portfolio_button(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Fetch data using the new helper
        holdings, transactions = await self.market_system.get_portfolio_data(interaction.user.id)
        
        if not holdings:
            await interaction.followup.send("You don't own any stocks.", ephemeral=True)
            return
            
        # Send V2 Portfolio View
        view = StockPortfolioView(self.market_system, interaction.user.id, holdings, transactions)
        await interaction.followup.send(view=view, ephemeral=True)

    async def refresh_button(self, interaction: discord.Interaction):
        # "Show All Stocks" button
        if not self.market_system.stocks_cache:
             await interaction.response.send_message("Market is empty.", ephemeral=True)
             return
             
        # Defer to fetch data
        await interaction.response.defer(ephemeral=True)
        
        # Fetch circulation data
        held_counts = await self.market_system.db.stock.get_held_shares_counts()
             
        # Send the V2 List View ephemerally
        view = StockListView(self.market_system, held_counts)
        await interaction.followup.send(view=view, ephemeral=True)
