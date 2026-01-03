import discord
from redbot.core import commands, checks, app_commands
from redbot.core.utils.chat_formatting import humanize_number, box
from ..market_views import StockDashboardView, StockTransactionModal

class StockCommands:
    """Stock Market Commands for Unicornia"""

    @commands.hybrid_group(name="stock", aliases=["market", "stocks"])
    async def stock_group(self, ctx):
        """Stock Market commands"""
        pass

    @stock_group.command(name="list", aliases=["all", "prices"])
    async def stock_list(self, ctx):
        """View all active stocks and their prices."""
        stocks = self.market_system.stocks_cache.values()
        if not stocks:
            await ctx.send("The Stock Market is currently empty.")
            return

        embed = discord.Embed(title="📈 Unicornia Stock Exchange", color=discord.Color.gold())
        
        description = ""
        for s in stocks:
            price = s['price']
            prev = s['previous_price']
            change = price - prev
            change_pct = (change / prev * 100) if prev > 0 else 0
            
            arrow = "🟢" if change >= 0 else "🔴"
            
            description += f"{s['emoji']} **{s['symbol']}**\n"
            description += f"Price: {price:,} {arrow} ({change_pct:+.1f}%)\n"
            description += f"Vol: {s['total_shares']:,} shares\n\n"
            
        embed.description = description
        embed.set_footer(text="Use [p]stock buy <ticker> <amount> to invest!")
        
        await ctx.send(embed=embed)

    @stock_group.command(name="buy")
    @app_commands.describe(ticker="Stock Symbol", amount="Number of shares")
    async def stock_buy(self, ctx, ticker: str, amount: int):
        """Buy stocks."""
        success, msg = await self.market_system.buy_stock(ctx.author, ticker, amount)
        if success:
            await ctx.send(f"<a:zz_YesTick:729318762356015124> {msg}")
        else:
            await ctx.send(f"❌ {msg}")

    @stock_group.command(name="sell")
    @app_commands.describe(ticker="Stock Symbol", amount="Number of shares")
    async def stock_sell(self, ctx, ticker: str, amount: int):
        """Sell stocks."""
        success, msg = await self.market_system.sell_stock(ctx.author, ticker, amount)
        if success:
            await ctx.send(f"<a:zz_YesTick:729318762356015124> {msg}")
        else:
            await ctx.send(f"❌ {msg}")

    @stock_group.command(name="portfolio", aliases=["holdings"])
    async def stock_portfolio(self, ctx, user: discord.Member = None):
        """View your stock portfolio."""
        user = user or ctx.author
        holdings = await self.market_system.db.stock.get_user_holdings(user.id)
        
        if not holdings:
            await ctx.send(f"{user.display_name} has no stock holdings.")
            return

        embed = discord.Embed(title=f"📈 Portfolio: {user.display_name}", color=discord.Color.blue())
        
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
        
        await ctx.send(embed=embed)

    @stock_group.command(name="dashboard")
    @checks.admin_or_permissions(manage_guild=True)
    async def stock_dashboard(self, ctx, channel: discord.TextChannel = None):
        """Create a persistent Stock Market Dashboard."""
        channel = channel or ctx.channel
        
        embed = discord.Embed(
            title="🏙️ Unicornia Stock Exchange",
            description="Welcome to the Market! Use the buttons below to trade.\nPrices update hourly.",
            color=discord.Color.purple()
        )
        embed.set_image(url="https://media.discordapp.net/attachments/1000/market_banner.png") # Placeholder
        
        # Initial Population of Top 20
        stocks = self.market_system.stocks_cache.values()
        if stocks:
            desc = ""
            sorted_stocks = sorted(stocks, key=lambda s: s['total_shares'], reverse=True)[:20]
            for s in sorted_stocks:
                price = s['price']
                prev = s['previous_price']
                change = price - prev
                change_pct = (change / prev * 100) if prev > 0 else 0
                arrow = "🟢" if change >= 0 else "🔴"
                desc += f"{s['emoji']} **{s['symbol']}**: {price:,} {arrow} ({change_pct:+.1f}%)\n"
            
            embed.add_field(name="📊 Top 20 Stocks", value=desc, inline=False)
        else:
            embed.add_field(name="📊 Top 20 Stocks", value="Market is empty.", inline=False)

        view = StockDashboardView(self.market_system)
        msg = await channel.send(embed=embed, view=view)
        
        # Save message ID if we want to update it
        # self.market_system.market_channel_id = channel.id
        # self.market_system.dashboard_message_id = msg.id
        
        # Save to Config
        cog = ctx.cog # ctx.cog is Unicornia
        await cog.config.guild(ctx.guild).market_channel.set(channel.id)
        await cog.config.guild(ctx.guild).market_message.set(msg.id)
        
        await ctx.send(f"Dashboard created in {channel.mention}.")

    @stock_group.command(name="ipo")
    @checks.is_owner()
    async def stock_ipo(self, ctx, symbol: str, price: int, emoji: str, *, name: str):
        """Launch a new stock (IPO)."""
        if price <= 0:
            await ctx.send("Price must be positive.")
            return

        success = await self.market_system.register_stock(symbol, name, emoji, price)
        if success:
            await ctx.send(f"🚀 IPO Successful! **{name} ({symbol})** is now trading at {price}!")
        else:
            await ctx.send("Failed to launch IPO. Symbol might already exist.")

    @stock_group.command(name="delist")
    @checks.is_owner()
    async def stock_delist(self, ctx, symbol: str):
        """Delist a stock (Delete it)."""
        # Confirmation?
        await self.market_system.db.stock.delete_stock(symbol)
        await self.market_system.initialize() # Refresh cache
        await ctx.send(f"🗑️ Delisted **{symbol}**.")

    @stock_group.command(name="cleanup")
    @checks.is_owner()
    async def stock_cleanup(self, ctx):
        """Clean up dead dashboard configurations."""
        guild = ctx.guild
        if not guild:
            await ctx.send("This command must be run in a server.")
            return
            
        cog = ctx.cog
        await cog.config.guild(guild).market_channel.clear()
        await cog.config.guild(guild).market_message.clear()
        
        await ctx.send("Dashboard configuration cleared for this server. The bot will stop trying to update it.")
