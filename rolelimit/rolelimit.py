"""Keep members to one role out of a configured set.

Merges jenjam's ``colourlimit`` and ``rolelimit`` cogs. Both keep reading the
Config data the originals saved (same identifiers and cog names), so there is
nothing to migrate.

- colourlimit: when a member gains a listed role, the listed roles they already had
  are removed, so the newest one stays.
- rolelimit: a member keeps only the listed role that comes last in the list
  (the list runs lowest to highest).
"""

import logging
from collections.abc import Iterable

import discord
from redbot.core import Config, commands
from redbot.core.utils import AsyncIter
from redbot.core.utils.chat_formatting import humanize_list
from redbot.core.utils.predicates import MessagePredicate

log = logging.getLogger("red.kirin-cogs.rolelimit")

# Identifiers of the original cogs; changing them would orphan the saved settings.
ROLELIMIT_IDENTIFIER = 1471894719841
COLOURLIMIT_IDENTIFIER = 147189471982418789741


def _role_ids(value: object) -> list[int]:
    """Config data is untrusted: keep only the ints from a list."""
    if not isinstance(value, list):
        return []
    return [r for r in value if isinstance(r, int) and not isinstance(r, bool)]


def colour_roles_to_remove(limit_ids: Iterable[int], before_ids: set[int], added_ids: set[int]) -> set[int]:
    """Listed roles held before the update, if the update added a listed role."""
    limit = set(limit_ids)
    if not limit & added_ids:
        return set()
    return limit & before_ids


def ranked_roles_to_remove(limit_ids: Iterable[int], member_ids: set[int]) -> set[int]:
    """Every held listed role except the one that comes last in the list."""
    held = [r for r in dict.fromkeys(limit_ids) if r in member_ids]
    return set(held[:-1])


class RoleLimit(commands.Cog):
    """Limit members to one role out of a set (colour roles and ranked roles)."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=ROLELIMIT_IDENTIFIER)
        self.config.register_guild(roles=[])
        self.colour_config = Config.get_conf(None, identifier=COLOURLIMIT_IDENTIFIER, cog_name="ColourLimit")
        self.colour_config.register_guild(roles=[])

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """This cog stores no user data."""
        return

    async def _remove_roles(self, member: discord.Member, role_ids: set[int], reason: str) -> None:
        guild = member.guild
        if not role_ids or not guild.me.guild_permissions.manage_roles:
            return
        roles = [r for r in (guild.get_role(i) for i in role_ids) if r is not None and r.is_assignable()]
        if not roles:
            return
        try:
            await member.remove_roles(*roles, reason=reason)
        except discord.NotFound:
            pass
        except discord.HTTPException:
            log.warning("Could not remove %s from %s in %s", roles, member.id, guild.id, exc_info=True)

    async def _clean_ranked(self, member: discord.Member) -> None:
        limit_ids = _role_ids(await self.config.guild(member.guild).roles())
        member_ids = {r.id for r in member.roles}
        await self._remove_roles(member, ranked_roles_to_remove(limit_ids, member_ids), "Role limit")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        before_ids = {r.id for r in before.roles}
        after_ids = {r.id for r in after.roles}
        added_ids = after_ids - before_ids
        if not added_ids:
            return
        if await self.bot.cog_disabled_in_guild(self, after.guild):
            return

        colour_ids = _role_ids(await self.colour_config.guild(after.guild).roles())
        to_remove = colour_roles_to_remove(colour_ids, before_ids, added_ids) & after_ids
        await self._remove_roles(after, to_remove, "Colour limit: newer colour role added")

        # Re-read the member's roles as they stand after the colour pass.
        remaining = after_ids - to_remove
        limit_ids = _role_ids(await self.config.guild(after.guild).roles())
        await self._remove_roles(after, ranked_roles_to_remove(limit_ids, remaining), "Role limit")

    @staticmethod
    def _describe(guild: discord.Guild, role_ids: list[int]) -> str:
        if not role_ids:
            return "none"
        return humanize_list([f"{r} ({guild.get_role(r) or 'deleted role'})" for r in role_ids])

    # --- colourlimit -------------------------------------------------------

    @commands.group()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def colourlimit(self, ctx: commands.Context) -> None:
        """Only let members keep the newest of these roles."""

    @colourlimit.command(name="set")
    async def colourlimit_set(self, ctx: commands.Context, *roles: discord.Role) -> None:
        """Replace the colour role list."""
        assert ctx.guild is not None
        await self.colour_config.guild(ctx.guild).roles.set([r.id for r in roles])
        await self.colourlimit_listroles(ctx)

    @colourlimit.command(name="listroles")
    async def colourlimit_listroles(self, ctx: commands.Context) -> None:
        """Show the colour role list."""
        assert ctx.guild is not None
        roles = _role_ids(await self.colour_config.guild(ctx.guild).roles())
        await ctx.send(f"Roles to limit (to newest): {self._describe(ctx.guild, roles)}")

    @colourlimit.command(name="clear")
    async def colourlimit_clear(self, ctx: commands.Context) -> None:
        """Empty the colour role list."""
        assert ctx.guild is not None
        await self.colour_config.guild(ctx.guild).roles.set([])
        await self.colourlimit_listroles(ctx)

    # --- rolelimit ---------------------------------------------------------

    @commands.group()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def rolelimit(self, ctx: commands.Context) -> None:
        """Only let members keep the highest of these roles."""

    @rolelimit.command(name="set")
    async def rolelimit_set(self, ctx: commands.Context, *roles: discord.Role) -> None:
        """Replace the ranked role list, lowest first."""
        assert ctx.guild is not None
        await self.config.guild(ctx.guild).roles.set([r.id for r in roles])
        await self.rolelimit_listroles(ctx)

    @rolelimit.command(name="listroles")
    async def rolelimit_listroles(self, ctx: commands.Context) -> None:
        """Show the ranked role list."""
        assert ctx.guild is not None
        roles = _role_ids(await self.config.guild(ctx.guild).roles())
        await ctx.send(f"Roles to limit (lowest to highest): {self._describe(ctx.guild, roles)}")

    @rolelimit.command(name="clear")
    async def rolelimit_clear(self, ctx: commands.Context) -> None:
        """Empty the ranked role list."""
        assert ctx.guild is not None
        await self.config.guild(ctx.guild).roles.set([])
        await self.rolelimit_listroles(ctx)

    @rolelimit.command(name="scan")
    @commands.bot_has_permissions(manage_roles=True)
    async def rolelimit_scan(self, ctx: commands.Context) -> None:
        """Apply the ranked role limit to every member."""
        assert ctx.guild is not None
        await ctx.send(
            "Are you sure you want to scan all members and apply the rolelimit? Answer yes/no, timeout in 30 seconds"
        )
        pred = MessagePredicate.yes_or_no(ctx)
        try:
            await self.bot.wait_for("message", check=pred, timeout=30.0)
        except TimeoutError:
            await ctx.send("Scan cancelled")
            return
        if not pred.result:
            await ctx.send("Scan cancelled")
            return
        await ctx.send("Now scanning members")
        members = list(ctx.guild.members)
        async with ctx.typing():
            async for member in AsyncIter(members, steps=50):
                await self._clean_ranked(member)
        await ctx.send(f"Scanned {len(members)} members")
