"""The staff site's Unicornia pages: member lookup, economy, config and stock market.

Read-only by construction: every route is a GET, so there is nothing to change and nothing to forge. The data comes
from the Unicornia cog's read helpers (reached with bot.get_cog), never from its database directly.
"""

from typing import TYPE_CHECKING, Any

import discord
from aiohttp import web

from .member import _rank, _timestamp

if TYPE_CHECKING:
    from .dashboard import Dashboard

MAX_QUERY = 100
MAX_MATCHES = 50
TRANSACTIONS = 100


class StaffUnicornia:
    def __init__(self, cog: "Dashboard") -> None:
        self.cog = cog

    def add_routes(self, app: web.Application) -> None:
        app.router.add_get("/unicornia/members", self.members)
        app.router.add_get(r"/unicornia/members/{user_id:\d{1,20}}", self.member)
        app.router.add_get("/unicornia/economy", self.economy)
        app.router.add_get("/unicornia/config", self.config)
        app.router.add_get("/unicornia/market", self.market)

    def _unicornia(self, request: web.Request) -> tuple[discord.Guild, Any]:
        uni = self.cog.bot.get_cog("Unicornia")
        guild = self.cog.guild()
        if uni is None or guild is None:
            page = self.cog._message(
                request, 503, "Not available", "Unicornia isn't loaded right now. Try again later."
            )
            raise web.HTTPServiceUnavailable(text=page.text, content_type="text/html")
        return guild, uni

    def _render(self, request: web.Request, template: str, **context: Any) -> web.Response:
        return self.cog._render(request, f"unicornia/{template}", **context)

    async def members(self, request: web.Request) -> web.StreamResponse:
        guild, _uni = self._unicornia(request)
        query = request.query.get("q", "").strip()[:MAX_QUERY]
        if query.isdigit():
            raise web.HTTPFound(f"/unicornia/members/{query}")
        needle = query.casefold()
        matches = (
            [
                m
                for m in guild.members
                if not m.bot and (needle in m.name.casefold() or needle in m.display_name.casefold())
            ][:MAX_MATCHES]
            if needle
            else []
        )
        return self._render(request, "members.html", q=query, matches=matches, more=len(matches) == MAX_MATCHES)

    async def member(self, request: web.Request) -> web.StreamResponse:
        guild, uni = self._unicornia(request)
        user_id = int(request.match_info["user_id"])
        summary = await uni.member_summary(guild, user_id, transactions=TRANSACTIONS, details=True)
        for transaction in summary["transactions"]:
            transaction["timestamp"] = _timestamp(transaction["date"])
        return self._render(
            request,
            "member.html",
            user_id=user_id,
            member=guild.get_member(user_id),
            me=summary,
            rank=_rank(summary["rank"], len(await uni.xp_ranking(guild))),
        )

    async def economy(self, request: web.Request) -> web.StreamResponse:
        guild, uni = self._unicornia(request)
        return self._render(request, "economy.html", richest=await uni.richest(guild), house=await uni.house_stats())

    def _channels(self, guild: discord.Guild, ids: object) -> list[dict[str, Any]]:
        """Channels by name; ones that no longer exist by ID, marked missing."""
        shown = []
        for channel_id in ids if isinstance(ids, list) else []:
            channel = guild.get_channel_or_thread(channel_id) if isinstance(channel_id, int) else None
            shown.append({"name": f"#{channel.name}" if channel else str(channel_id), "missing": channel is None})
        return shown

    def _role(self, guild: discord.Guild, role_id: object) -> dict[str, Any]:
        role = guild.get_role(role_id) if isinstance(role_id, int) else None
        return {"name": f"@{role.name}" if role else str(role_id), "missing": role is None}

    async def config(self, request: web.Request) -> web.StreamResponse:
        guild, uni = self._unicornia(request)
        snapshot = await uni.config_snapshot(guild)
        return self._render(
            request,
            "config.html",
            settings=snapshot["settings"],
            channels={
                "XP channels": self._channels(guild, snapshot["xp_channels"]),
                "Double-XP channels": self._channels(guild, snapshot["double_xp_channels"]),
                "Currency-generation channels": self._channels(guild, snapshot["generation_channels"]),
                "Stock dashboard channel": self._channels(guild, [c] if (c := snapshot["market_channel"]) else []),
            },
            excluded_roles=[self._role(guild, role_id) for role_id in snapshot["excluded_roles"]],
            role_rewards=[
                {"level": level, "role": self._role(guild, role_id), "remove": bool(remove)}
                for level, role_id, remove in snapshot["role_rewards"]
            ],
            currency_rewards=snapshot["currency_rewards"],
            whitelists={
                "Commands": {name: self._channels(guild, ids) for name, ids in snapshot["command_whitelist"].items()},
                "Systems": {name: self._channels(guild, ids) for name, ids in snapshot["system_whitelist"].items()},
            },
        )

    async def market(self, request: web.Request) -> web.StreamResponse:
        _guild, uni = self._unicornia(request)
        return self._render(request, "market.html", stocks=await uni.stocks())
