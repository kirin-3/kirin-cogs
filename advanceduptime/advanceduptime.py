"""Replace the core uptime command with one that shows extra stats.

Ported from Kreusada's ``advanceduptime`` (MIT, Copyright (c) Kreusada), which was
removed from Kreusada-Cogs in 2023. It keeps the original Config identifier and cog
name, so the saved settings carry over.

The original crashed on discord.py 2 (``bot.user.avatar_url``); this version fixes that
and reads its settings from Config instead of a cache.
"""

import logging
import math
from collections import Counter
from datetime import UTC, datetime, timedelta

import discord
import psutil
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import bold, box, humanize_number, humanize_timedelta

log = logging.getLogger("red.kirin-cogs.advanceduptime")

DEFAULT_GLOBAL = {
    "show_bot_stats": True,
    "show_latency_stats": True,
    "show_usage_stats": True,
    "show_system_uptime_stats": True,
}
UNITS = (("seconds", 1), ("minutes", 60), ("hours", 3600), ("days", 86400))


def unit_breakdown(delta: timedelta) -> str:
    """The whole delta expressed in each unit, as a diff block body."""
    lines = []
    for name, size in UNITS:
        count = math.floor(delta.total_seconds() / size)
        lines.append(f"+ {humanize_number(count)} {name[:-1] if count == 1 else name}")
    return "\n".join(lines)


def uptime_field(subject: str, delta: timedelta) -> str:
    human = humanize_timedelta(timedelta=delta) or "less than one second"
    return f"{subject} has been up for {bold(human)}." + box(unit_breakdown(delta), lang="diff")


class AdvancedUptime(commands.Cog):
    """Show [botname]'s uptime, with extra stats."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.commands_run: Counter[str] = Counter()
        self.config = Config.get_conf(self, identifier=4589035903485, force_registration=True)
        self.config.register_global(**DEFAULT_GLOBAL)
        self._core_uptime: commands.Command | None = None

    async def cog_load(self) -> None:
        # discord.py runs cog_load before adding our commands, so the core one must go first.
        self._core_uptime = self.bot.remove_command("uptime")  # pyright: ignore[reportAttributeAccessIssue]

    async def cog_unload(self) -> None:
        # Our commands are already removed by the time cog_unload runs.
        if self._core_uptime is not None:
            self.bot.add_command(self._core_uptime)

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """This cog stores no user data."""
        return

    @commands.Cog.listener()
    async def on_command(self, ctx: commands.Context) -> None:
        if ctx.guild is not None and await self.bot.cog_disabled_in_guild(self, ctx.guild):
            return
        if not await self.config.show_usage_stats():
            return
        self.commands_run[str(ctx.command)] += 1

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.bot_has_permissions(embed_links=True)
    async def uptime(self, ctx: commands.Context) -> None:
        """Shows [botname]'s uptime."""
        settings = await self.config.all()
        me = self.bot.user
        assert me is not None
        # Red stores uptime as a naive UTC datetime.
        bot_delta = discord.utils.utcnow() - self.bot.uptime.replace(tzinfo=UTC)

        embed = discord.Embed(
            title="\N{LARGE GREEN CIRCLE} Uptime Information",
            color=await ctx.embed_colour(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(name=str(me), icon_url=me.display_avatar.url)
        embed.add_field(name="Bot Uptime Details", value=uptime_field(str(me), bot_delta), inline=False)

        if settings["show_system_uptime_stats"]:
            system_delta = discord.utils.utcnow() - datetime.fromtimestamp(psutil.boot_time(), UTC)
            embed.add_field(
                name="System Uptime Details", value=uptime_field("The bot's system", system_delta), inline=False
            )

        if settings["show_bot_stats"]:
            app_info = await self.bot.application_info()
            stats = {
                "Users": humanize_number(len(self.bot.users)),
                "Owner": app_info.team.name if app_info.team else str(app_info.owner),
                "Servers": humanize_number(len(self.bot.guilds)),
                "Commands available": humanize_number(len(set(self.bot.walk_commands()))),
            }
            embed.add_field(
                name="Bot Stats", value=box("\n".join(f"{k}: {v}" for k, v in stats.items()), lang="yaml"), inline=False
            )

        if settings["show_latency_stats"]:
            lines = [f"Bot latency: {round(self.bot.latency * 1000, 2)}ms"]
            shards = self.bot.latencies
            lines += [f"Shard {shard + 1}/{len(shards)}: {int(latency * 1000)}ms" for shard, latency in shards]
            embed.add_field(name="Shard and Latency Stats", value=box("\n".join(lines), lang="yaml"), inline=False)

        if settings["show_usage_stats"] and self.commands_run:
            embed.add_field(name="Command usage since this cog has been loaded", value=self._usage_text(), inline=False)

        await ctx.send(embed=embed)

    def _usage_text(self) -> str:
        ranked = self.commands_run.most_common()

        def times(n: int) -> str:
            return "once" if n == 1 else f"{n} times"

        text = f"The most used command whilst the bot has been online is `{ranked[0][0]}`, which has been used {times(ranked[0][1])}."
        if len(ranked) > 1:
            text += f"\n\nThe least used command is `{ranked[-1][0]}`, which has been used {times(ranked[-1][1])}."
        return text

    @commands.group()  # pyright: ignore[reportArgumentType]
    @commands.is_owner()
    async def uptimeset(self, ctx: commands.Context) -> None:
        """Settings for the uptime command."""

    async def _toggle(self, ctx: commands.Context, key: str, label: str, value: bool) -> None:
        await self.config.set_raw(key, value=value)  # pyright: ignore[reportCallIssue]
        await ctx.send(f"{label} {'enabled' if value else 'disabled'}.")

    @uptimeset.command(name="botstats")
    async def uptimeset_botstats(self, ctx: commands.Context, true_or_false: bool) -> None:
        """Toggles whether bot stats are shown in the uptime command."""
        await self._toggle(ctx, "show_bot_stats", "Bot stats", true_or_false)

    @uptimeset.command(name="latencystats")
    async def uptimeset_latencystats(self, ctx: commands.Context, true_or_false: bool) -> None:
        """Toggles whether latency stats are shown in the uptime command."""
        await self._toggle(ctx, "show_latency_stats", "Latency stats", true_or_false)

    @uptimeset.command(name="sysuptime")
    async def uptimeset_sysuptime(self, ctx: commands.Context, true_or_false: bool) -> None:
        """Toggles whether system uptime stats are shown in the uptime command."""
        await self._toggle(ctx, "show_system_uptime_stats", "System uptime stats", true_or_false)

    @uptimeset.command(name="usagestats")
    async def uptimeset_usagestats(self, ctx: commands.Context, true_or_false: bool) -> None:
        """Toggles whether usage stats are shown and tracked."""
        await self._toggle(ctx, "show_usage_stats", "Usage stats", true_or_false)
        if not true_or_false:
            self.commands_run.clear()

    @uptimeset.command(name="settings", aliases=["showsettings"])
    async def uptimeset_settings(self, ctx: commands.Context) -> None:
        """Shows the settings for the uptime command."""
        settings = await self.config.all()
        await ctx.send(
            "\n".join(
                f"{bold(key.replace('_', ' ').capitalize())}: {settings[key]}"
                for key in sorted(DEFAULT_GLOBAL, key=len)
            )
        )
