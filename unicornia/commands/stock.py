import discord
from redbot.core import app_commands, checks, commands

from ..market_views import (
    StockDashboardView,
    StockListView,
    StockPortfolioView,
)
from ..mixins import UnicorniaMixinBase
from ..stock_market import UnwindOutcome


def format_unwind_outcome(outcome: UnwindOutcome, *, confirmed: bool) -> str:
    """Render the same complete unwind plan for dry runs and executions."""
    plan = outcome.plan
    if outcome.aborted:
        heading = "## Stock Unwind Aborted"
        status = "Nothing was changed because one or more holdings have no resolvable cost basis."
    elif outcome.executed:
        heading = "## Stock Unwind Complete"
        status = "All planned refunds were paid and the market was reset."
    elif confirmed and not plan.refunds and not plan.unresolvable:
        heading = "## Stock Unwind — No Changes Needed"
        status = "The market has no positions to refund. Nothing was changed."
    else:
        heading = "## Stock Unwind Dry Run"
        status = "Nothing was changed. Use `[p]stock unwind confirm` to execute this exact operation."

    lines = [
        heading,
        status,
        f"Users affected: **{plan.users_affected:,}**",
        f"Holdings to clear: **{len(plan.refunds):,}**",
        f"Total refund: **{plan.total_refund:,}**",
        f"Unresolvable holdings: **{len(plan.unresolvable):,}**",
    ]
    if not plan.refunds and not plan.unresolvable:
        lines.append("There is nothing to refund.")
    if plan.unresolvable:
        lines.append("\nUnresolvable positions (repair `AverageCost` before confirmation):")
        lines.extend(
            f"- User `{item.user_id}` — `{item.symbol}` — {item.shares:,} shares" for item in plan.unresolvable
        )
    if confirmed and outcome.aborted:
        lines.append("\nNo run identifier was created and no refund was attempted.")
    return "\n".join(lines)


async def send_in_chunks(ctx, content: str) -> None:
    """Send an audit report without exceeding Discord's message limit."""
    chunk = ""
    for line in content.splitlines(keepends=True):
        if chunk and len(chunk) + len(line) > 1900:
            await ctx.send(chunk)
            chunk = ""
        chunk += line
    if chunk:
        await ctx.send(chunk)


class StockCommands(UnicorniaMixinBase):
    """Stock Market Commands for Unicornia"""

    async def ticker_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        stocks = self.market_system.stocks_cache.values()
        choices = []
        for s in stocks:
            if current.upper() in s["symbol"] or current.lower() in s["name"].lower():
                choices.append(app_commands.Choice(name=f"{s['symbol']} - {s['name']}", value=s["symbol"]))
        return choices[:25]

    @commands.hybrid_group(name="stock", aliases=["market", "stocks"])  # type: ignore[arg-type]
    async def stock_group(self, ctx):
        """
        Invest in the Stock Market.

        Buy and sell stocks to grow your wealth.

        **Syntax**
        `[p]stock <subcommand>`
        """
        pass

    @stock_group.command(name="list", aliases=["all", "prices"])
    async def stock_list(self, ctx):
        """
        View active stocks.

        Shows current price and price changes.

        **Syntax**
        `[p]stock list`
        """
        if not self.market_system.stocks_cache:
            await ctx.send("The Stock Market is currently empty.")
            return

        # Fetch circulation data
        held_counts = await self.market_system.db.stock.get_held_shares_counts()

        # Send V2 Paginated View
        view = StockListView(self.market_system, held_counts)
        await ctx.send(view=view)

    @stock_group.command(name="buy")
    @app_commands.describe(ticker="Stock Symbol", amount="Number of shares")
    @app_commands.autocomplete(ticker=ticker_autocomplete)  # type: ignore[arg-type]
    async def stock_buy(self, ctx, ticker: str, amount: int):
        """
        Buy shares of a stock.

        **Syntax**
        `[p]stock buy <ticker> <amount>`

        **Examples**
        `[p]stock buy UNI 10`
        """
        success, msg = await self.market_system.buy_stock(ctx.author, ticker, amount)
        if success:
            await ctx.send(f"<a:zz_YesTick:729318762356015124> {msg}")
        else:
            await ctx.send(f"❌ {msg}")

    @stock_group.command(name="sell")
    @app_commands.describe(ticker="Stock Symbol", amount="Number of shares")
    @app_commands.autocomplete(ticker=ticker_autocomplete)  # type: ignore[arg-type]
    async def stock_sell(self, ctx, ticker: str, amount: int):
        """
        Sell shares of a stock.

        **Syntax**
        `[p]stock sell <ticker> <amount>`

        **Examples**
        `[p]stock sell UNI 5`
        """
        success, msg = await self.market_system.sell_stock(ctx.author, ticker, amount)
        if success:
            await ctx.send(f"<a:zz_YesTick:729318762356015124> {msg}")
        else:
            await ctx.send(f"❌ {msg}")

    @stock_group.command(name="unwind")
    @checks.is_owner()
    async def stock_unwind(self, ctx, confirmation: str | None = None):
        """Dry-run or confirm the owner-only market position unwind.

        **Syntax**
        `[p]stock unwind`
        `[p]stock unwind confirm`
        """
        confirmed = (confirmation or "").strip().lower() == "confirm"
        outcome = await self.market_system.unwind_market(confirm=confirmed)
        await send_in_chunks(ctx, format_unwind_outcome(outcome, confirmed=confirmed))

    @stock_group.command(name="portfolio", aliases=["holdings"])
    async def stock_portfolio(self, ctx, user: discord.Member | None = None):
        """
        View your portfolio.

        Shows your current holdings and profit/loss.

        **Syntax**
        `[p]stock portfolio [user]`
        """
        user = user or ctx.author

        # Fetch data
        holdings, transactions = await self.market_system.get_portfolio_data(user.id)

        if not holdings:
            await ctx.send(f"{user.display_name} has no stock holdings.")
            return

        # Send V2 View
        dividend_rows = await self.db.economy.get_dividend_history(user.id)
        latest_dividends: dict[str, int] = {}
        for row in dividend_rows:
            latest_dividends.setdefault(str(row["symbol"]), int(row["amount"]))
        view = StockPortfolioView(self.market_system, user.id, holdings, transactions, latest_dividends)
        await ctx.send(view=view)

    @stock_group.command(name="dividends", aliases=["yield"])
    async def stock_dividends(self, ctx):
        """View your stock-dividend history by period and symbol."""
        rows = await self.db.economy.get_dividend_history(ctx.author.id)
        if not rows:
            holdings = await self.db.stock.get_user_holdings(ctx.author.id)
            if not holdings:
                await ctx.send("You hold no shares, so you have no dividend history yet.")
            else:
                await ctx.send("You have not received a stock dividend yet.")
            return

        currency = await self.config.currency_symbol()
        lines = ["## Your Stock Dividends"]
        for row in rows[:25]:
            lines.append(
                f"- `{row['period_end']}` — **{row['symbol']}**: "
                f"{currency}{int(row['amount']):,} (weight {float(row['weight']):,.3f})"
            )
        await send_in_chunks(ctx, "\n".join(lines))

    @stock_group.command(name="dashboard")
    @checks.admin_or_permissions(manage_guild=True)
    async def stock_dashboard(self, ctx, channel: discord.TextChannel | None = None):
        """
        Create a live stock dashboard.

        **Admin/Manage Guild only.**

        **Syntax**
        `[p]stock dashboard [channel]`
        """
        channel = channel or ctx.channel
        assert isinstance(channel, discord.TextChannel)

        view = StockDashboardView(self.market_system)
        msg = await channel.send(view=view)  # No embed, components only

        # Save to Config
        cog = ctx.cog  # ctx.cog is Unicornia
        await cog.config.guild(ctx.guild).market_channel.set(channel.id)
        await cog.config.guild(ctx.guild).market_message.set(msg.id)

        await ctx.send(f"Dashboard created in {channel.mention}.")

    @stock_group.command(name="ipo")
    @checks.is_owner()
    async def stock_ipo(self, ctx, symbol: str, price: int, emoji: str, *, name: str):
        """
        Launch a new stock (IPO).

        **Owner only.**

        **Syntax**
        `[p]stock ipo <symbol> <price> <emoji> <name>`
        """
        if price <= 0:
            await ctx.send("Price must be positive.")
            return

        success = await self.market_system.register_stock(symbol, name, emoji, price)
        if success:
            await ctx.send(
                f"🚀 IPO Successful! **{name} ({symbol})** is now trading at {price} {self.market_system.currency_symbol}!"
            )
        else:
            await ctx.send("Failed to launch IPO. Symbol might already exist.")

    @stock_group.command(name="delist")
    @checks.is_owner()
    async def stock_delist(self, ctx, symbol: str):
        """
        Delist a stock.

        **Owner only.**

        **Syntax**
        `[p]stock delist <symbol>`
        """
        # Confirmation?
        await self.market_system.db.stock.delete_stock(symbol)
        await self.market_system.initialize()  # Refresh cache
        await ctx.send(f"🗑️ Delisted **{symbol}**.")

    @stock_group.command(name="cleanup")
    @checks.is_owner()
    async def stock_cleanup(self, ctx):
        """
        Cleanup dashboard config.

        **Owner only.**

        **Syntax**
        `[p]stock cleanup`
        """
        guild = ctx.guild
        if not guild:
            await ctx.send("This command must be run in a server.")
            return

        cog = ctx.cog
        await cog.config.guild(guild).market_channel.clear()
        await cog.config.guild(guild).market_message.clear()

        await ctx.send("Dashboard configuration cleared for this server. The bot will stop trying to update it.")
