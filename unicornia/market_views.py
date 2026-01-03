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

# --- Step 2: Selection Views (Ephemeral) ---

class StockBuySelectView(ui.View):
    def __init__(self, market_system, options: list[discord.SelectOption]):
        super().__init__(timeout=60)
        self.market_system = market_system
        
        # Select Menu
        self.select = ui.Select(
            placeholder="Select a stock to buy...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        symbol = self.select.values[0]
        # Open the Amount Modal
        await interaction.response.send_modal(StockAmountModal(self.market_system, "buy", symbol))

class StockSellSelectView(ui.View):
    def __init__(self, market_system, options: list[discord.SelectOption]):
        super().__init__(timeout=60)
        self.market_system = market_system
        
        # Select Menu
        self.select = ui.Select(
            placeholder="Select a stock to sell...",
            min_values=1,
            max_values=1,
            options=options
        )
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        symbol = self.select.values[0]
        # Open the Amount Modal
        await interaction.response.send_modal(StockAmountModal(self.market_system, "sell", symbol))

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
        container.add_item(ui.TextDisplay(content="## 🏙️ Unicornia Stock Exchange\nWelcome to the Market! Use the buttons below to trade.\nPrices update hourly."))
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
                line = f"{s['emoji']} **{s['symbol']}**: {price:,} {arrow} ({change_pct:+.1f}%) {extra_info}\n"
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

        # 3. Top 10 Most Held
        if self.market_system.top_held:
            held_text = generate_list_text(
                self.market_system.top_held,
                lambda s: f"| 👥 Owned: {s.get('held_shares', 0):,}"
            )
            container.add_item(ui.TextDisplay(content=f"### 🐋 Top 10 Most Held\n{held_text}"))
        else:
            container.add_item(ui.TextDisplay(content="### 📊 Market Status\nMarket is initializing or empty."))
            
        # Footer-ish
        container.add_item(ui.Separator())
        # Use Discord Timestamp <t:TIMESTAMP:R> for relative time
        ts = int(discord.utils.utcnow().timestamp())
        container.add_item(ui.TextDisplay(content=f"*Last Update: <t:{ts}:R>*"))
        
        # Interactive Controls (Must be wrapped in ActionRow)
        
        # Row 1: Buy/Sell
        buy_btn = ui.Button(label="Buy Stock", style=discord.ButtonStyle.success, custom_id="market:buy")
        sell_btn = ui.Button(label="Sell Stock", style=discord.ButtonStyle.danger, custom_id="market:sell")
        
        buy_btn.callback = self.buy_button
        sell_btn.callback = self.sell_button
        
        # Row 2: Portfolio/Show All
        portfolio_btn = ui.Button(label="My Portfolio", style=discord.ButtonStyle.primary, custom_id="market:portfolio")
        show_all_btn = ui.Button(label="Show All Stocks", style=discord.ButtonStyle.secondary, custom_id="market:show_all")
        
        portfolio_btn.callback = self.portfolio_button
        show_all_btn.callback = self.refresh_button # Reusing the refresh logic which shows all
        
        container.add_item(ui.ActionRow(buy_btn, sell_btn))
        container.add_item(ui.ActionRow(portfolio_btn, show_all_btn))
        
        self.add_item(container)

    async def buy_button(self, interaction: discord.Interaction):
        # Prepare stock options
        stocks = sorted(self.market_system.stocks_cache.values(), key=lambda s: s['symbol'])
        if not stocks:
            await interaction.response.send_message("Market is empty.", ephemeral=True)
            return
            
        # Create select options (Limit 25)
        options = []
        for s in stocks[:25]:
            options.append(discord.SelectOption(
                label=f"{s['symbol']} - {s['price']:,}",
                value=s['symbol'],
                emoji=s['emoji'],
                description=s['name'][:100]
            ))
            
        # Send Ephemeral View for Selection
        await interaction.response.send_message(
            "Select a stock to buy:", 
            view=StockBuySelectView(self.market_system, options), 
            ephemeral=True
        )

    async def sell_button(self, interaction: discord.Interaction):
        # Fetch holdings first
        holdings = await self.market_system.db.stock.get_user_holdings(interaction.user.id)
        if not holdings:
            await interaction.response.send_message("You don't own any stocks to sell.", ephemeral=True)
            return
            
        # Create select options (Limit 25)
        options = []
        for h in holdings[:25]:
            options.append(discord.SelectOption(
                label=f"{h['symbol']} (Owned: {h['amount']:,})",
                value=h['symbol'],
                emoji=h['emoji'],
                description=f"Current Price: {h['current_price']:,}"
            ))
            
        # Send Ephemeral View for Selection
        await interaction.response.send_message(
            "Select a stock to sell:", 
            view=StockSellSelectView(self.market_system, options), 
            ephemeral=True
        )

    async def portfolio_button(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        holdings = await self.market_system.db.stock.get_user_holdings(interaction.user.id)
        if not holdings:
            await interaction.followup.send("You don't own any stocks.", ephemeral=True)
            return
            
        embed = discord.Embed(title="📈 My Portfolio", color=discord.Color.blue())
        
        total_value = 0
        total_cost_basis = 0
        
        description = ""
        for h in holdings:
            symbol = h['symbol']
            amount = h['amount']
            avg_cost = h['average_cost']
            current_price = h['current_price']
            emoji = h['emoji']
            
            value = amount * current_price
            cost = amount * avg_cost
            profit = value - cost
            profit_pct = (profit / cost * 100) if cost > 0 else 0
            
            total_value += value
            total_cost_basis += cost
            
            arrow = "🟢" if profit >= 0 else "🔴"
            description += f"**{emoji} {symbol}**: {amount:,} shares\n"
            description += f"Value: {value:,} (Avg: {avg_cost:.1f})\n"
            description += f"{arrow} P/L: {profit:,.0f} ({profit_pct:+.1f}%)\n\n"
            
        total_profit = total_value - total_cost_basis
        total_profit_pct = (total_profit / total_cost_basis * 100) if total_cost_basis > 0 else 0
        
        embed.description = description
        embed.set_footer(text=f"Total Value: {total_value:,} | Total P/L: {total_profit:,.0f} ({total_profit_pct:+.1f}%)")
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def refresh_button(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        stocks = self.market_system.stocks_cache.values()
        if not stocks:
            await interaction.followup.send("Market is closed/empty.", ephemeral=True)
            return

        embed = discord.Embed(title="📊 Live Prices (All Stocks)", color=discord.Color.gold())
        desc = ""
        for s in stocks:
            price = s['price']
            prev = s['previous_price']
            change = price - prev
            change_pct = (change / prev * 100) if prev > 0 else 0
            arrow = "🟢" if change >= 0 else "🔴"
            
            desc += f"{s['emoji']} **{s['symbol']}**: {price:,} {arrow} ({change_pct:+.1f}%)\n"
            
        embed.description = desc
        await interaction.followup.send(embed=embed, ephemeral=True)
