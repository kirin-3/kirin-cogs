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

class StockDashboardView(ui.View):
    def __init__(self, market_system):
        super().__init__(timeout=None) # Persistent view
        self.market_system = market_system

    @ui.button(label="Buy Stock", style=discord.ButtonStyle.success, custom_id="market:buy")
    async def buy_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(StockTransactionModal(self.market_system, "buy"))

    @ui.button(label="Sell Stock", style=discord.ButtonStyle.danger, custom_id="market:sell")
    async def sell_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(StockTransactionModal(self.market_system, "sell"))

    @ui.button(label="My Portfolio", style=discord.ButtonStyle.primary, custom_id="market:portfolio")
    async def portfolio_button(self, interaction: discord.Interaction, button: ui.Button):
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

    @ui.button(label="Refresh Board", style=discord.ButtonStyle.secondary, custom_id="market:refresh")
    async def refresh_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        # Trigger dashboard update manually? 
        # Usually dashboard updates automatically on tick.
        # Here we can just reply with ephemeral updated pricing?
        # Or force update the main message if we can (rate limits).
        # Let's just send ephemeral prices.
        
        stocks = self.market_system.stocks_cache.values()
        if not stocks:
            await interaction.followup.send("Market is closed/empty.", ephemeral=True)
            return

        embed = discord.Embed(title="📊 Live Prices (Snapshot)", color=discord.Color.gold())
        desc = ""
        for s in stocks:
            # Replicate dashboard row format
            price = s['price']
            prev = s['previous_price']
            change = price - prev
            change_pct = (change / prev * 100) if prev > 0 else 0
            arrow = "🟢" if change >= 0 else "🔴"
            
            desc += f"{s['emoji']} **{s['symbol']}**: {price:,} {arrow} ({change_pct:+.1f}%)\n"
            
        embed.description = desc
        await interaction.followup.send(embed=embed, ephemeral=True)
