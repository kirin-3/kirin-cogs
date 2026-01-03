"""
Market UI Components for Unicornia Stock Exchange
"""

import discord
from discord import ui
from redbot.core.utils.chat_formatting import humanize_number

class StockTransactionModal(ui.Modal):
    def __init__(self, market_system, transaction_type: str, ticker: str = None):
        super().__init__(title=f"{transaction_type.title()} Stock")
        self.market_system = market_system
        self.transaction_type = transaction_type # "buy" or "sell"
        
        self.ticker_input = ui.TextInput(
            label="Stock Ticker (Symbol)",
            placeholder="e.g. ROCKET",
            default=ticker or "",
            min_length=1,
            max_length=10,
            style=discord.TextStyle.short
        )
        self.add_item(self.ticker_input)
        
        self.amount_input = ui.TextInput(
            label="Amount (Shares)",
            placeholder="Enter number of shares",
            min_length=1,
            max_length=10,
            style=discord.TextStyle.short
        )
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        symbol = self.ticker_input.value.strip().upper()
        amount_str = self.amount_input.value.strip()
        
        if not amount_str.isdigit():
             await interaction.response.send_message("❌ Amount must be a positive number.", ephemeral=True)
             return
             
        amount = int(amount_str)
        if amount <= 0:
            await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
            return

        # Perform Transaction
        if self.transaction_type == "buy":
            success, msg = await self.market_system.buy_stock(interaction.user, symbol, amount)
        else:
            success, msg = await self.market_system.sell_stock(interaction.user, symbol, amount)
            
        if success:
            await interaction.response.send_message(f"<a:zz_YesTick:729318762356015124> {msg}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)

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
            
        # Top 15 Stocks
        stocks = self.market_system.stocks_cache.values()
        if stocks:
            desc = ""
            sorted_stocks = sorted(stocks, key=lambda s: s['total_shares'], reverse=True)[:15]
            
            for s in sorted_stocks:
                price = s['price']
                prev = s['previous_price']
                change = price - prev
                change_pct = (change / prev * 100) if prev > 0 else 0
                arrow = "🟢" if change >= 0 else "🔴"
                
                line = f"{s['emoji']} **{s['symbol']}**: {price:,} {arrow} ({change_pct:+.1f}%)\n"
                desc += line
                
            container.add_item(ui.TextDisplay(content=f"### 📊 Top 15 Stocks\n{desc}"))
        else:
            container.add_item(ui.TextDisplay(content="### 📊 Top 15 Stocks\nMarket is empty."))
            
        # Footer-ish
        container.add_item(ui.Separator())
        last_update = discord.utils.utcnow().strftime('%H:%M UTC')
        container.add_item(ui.TextDisplay(content=f"*Last Update: {last_update}*"))
        
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
        container.add_item(ui.ActionRow(portfolio_btn, refresh_btn))
        
        self.add_item(container)

    async def buy_button(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StockTransactionModal(self.market_system, "buy"))

    async def sell_button(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StockTransactionModal(self.market_system, "sell"))

    async def portfolio_button(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        holdings = await self.market_system.db.stock.get_user_holdings(interaction.user.id)
        if not holdings:
            await interaction.followup.send("You don't own any stocks.", ephemeral=True)
            return
            
        # We can stick to standard Embed for ephemeral responses (V2 limitation: ephemeral responses are messages too)
        # But if we want consistent V2 style, we could use a V2 View.
        # However, for simple ephemeral info, standard Embed is often cleaner/easier unless we need complex layout.
        # The guide says "When using V2 components... You CANNOT send embed".
        # So if we reply with ephemeral message, if we include V2 components we can't use Embed.
        # If we don't include components (just text/embed), it's a V1 message.
        # Let's stick to standard Embed for portfolio to avoid complexity, as it has no components.
        
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

        embed = discord.Embed(title="📊 Live Prices (Snapshot)", color=discord.Color.gold())
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
