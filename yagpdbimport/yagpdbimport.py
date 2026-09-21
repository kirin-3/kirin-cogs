import asyncio
import json
import logging
from datetime import datetime

import discord
from redbot.core import Config, commands

log = logging.getLogger("red.kirin_cogs.yagpdbimport")

YAGPDB_ID = 204255221017214977


def parse_yagpdb_warnings(raw: str, guild_id: int, points: int) -> list[tuple[int, str, dict]]:
    """Turn a YAGPDB getWarnings JSON dump into (user_id, warn_key, red_warning) for one guild.

    The key is a snowflake built from the warning's date, so Red's list sorts chronologically
    and re-importing the same warning produces the same key.
    """
    out = []
    for w in json.loads(raw):
        if int(w["GuildID"]) != guild_id:
            continue
        created = datetime.fromisoformat(w["CreatedAt"])
        key = str(discord.utils.time_snowflake(created) + int(w["ID"]) % (1 << 22))
        description = f"{w['Message']} (YAGPDB, {created:%Y-%m-%d}, by {w['AuthorUsernameDiscrim']})"
        out.append((int(w["UserID"]), key, {"points": points, "description": description, "mod": int(w["AuthorID"])}))
    return out


class YagpdbImport(commands.Cog):
    """Import warnings from YAGPDB into Red's Warnings cog."""

    def __init__(self, bot):
        self.bot = bot
        self.task: asyncio.Task | None = None
        # Red's core Warnings cog storage; same defaults it registers.
        self.warnings_config = Config.get_conf(None, identifier=5757575755, cog_name="Warnings")
        self.warnings_config.register_member(total_points=0, status="", warnings={})

    async def cog_unload(self) -> None:
        if self.task:
            self.task.cancel()

    @commands.group()
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def yagimport(self, ctx: commands.Context) -> None:
        """Import YAGPDB warnings."""

    @yagimport.command(name="start")
    async def yagimport_start(self, ctx: commands.Context, role: discord.Role, delay: float = 1.0) -> None:
        """Give `role` to every member, one every `delay` seconds, so YAGPDB's role trigger dumps their warnings.

        Members who already have the role are skipped, so running it again resumes where it stopped.
        """
        assert ctx.guild is not None
        if self.task and not self.task.done():
            await ctx.send("An import is already running. Use `yagimport stop` first.")
            return
        members = [m for m in ctx.guild.members if not m.bot and role not in m.roles]
        status = await ctx.send(f"Adding {role.name} to {len(members)} members...")
        self.task = asyncio.create_task(self._run(members, role, delay, status))
        self.task.add_done_callback(
            lambda t: t.cancelled() or t.exception() is None or log.error("Import loop crashed", exc_info=t.exception())
        )

    async def _run(
        self, members: list[discord.Member], role: discord.Role, delay: float, status: discord.Message
    ) -> None:
        failed = 0
        for i, member in enumerate(members, 1):
            try:
                await member.add_roles(role, reason="YAGPDB warnings import")
            except discord.HTTPException:
                failed += 1  # left the server, hierarchy, etc.
            if i % 100 == 0:
                await status.edit(content=f"Adding {role.name}: {i}/{len(members)} done, {failed} failed.")
            await asyncio.sleep(delay)
        await status.edit(
            content=f"Finished: {len(members)} members, {failed} failed. "
            f"Now run `yagimport scan` on the YAGPDB channel, then delete the {role.name} role."
        )

    @yagimport.command(name="stop")
    async def yagimport_stop(self, ctx: commands.Context) -> None:
        """Stop a running role loop."""
        if self.task and not self.task.done():
            self.task.cancel()
            await ctx.send("Stopped. Run `yagimport start` again to resume.")
        else:
            await ctx.send("Nothing is running.")

    @yagimport.command(name="scan")
    async def yagimport_scan(self, ctx: commands.Context, channel: discord.TextChannel, points: int = 1) -> None:
        """Import every warnings file YAGPDB posted in `channel` into Red's Warnings. Safe to re-run."""
        assert ctx.guild is not None
        by_user: dict[int, dict[str, dict]] = {}
        async with ctx.typing():
            async for msg in channel.history(limit=None):
                if msg.author.id != YAGPDB_ID:  # only trust files YAGPDB itself posted
                    continue
                for att in msg.attachments:
                    try:
                        rows = parse_yagpdb_warnings((await att.read()).decode(), ctx.guild.id, points)
                    except (ValueError, KeyError, TypeError):
                        continue  # not a warnings dump
                    for user_id, key, warning in rows:
                        by_user.setdefault(user_id, {})[key] = warning

            added = 0
            for user_id, new in by_user.items():
                group = self.warnings_config.member_from_ids(ctx.guild.id, user_id)
                async with group.warnings() as warns:
                    fresh = {k: v for k, v in new.items() if k not in warns}
                    ordered = sorted({**warns, **fresh}.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)
                    warns.clear()
                    warns.update(ordered)
                if fresh:
                    await group.total_points.set(await group.total_points() + sum(w["points"] for w in fresh.values()))
                added += len(fresh)
        await ctx.send(f"Imported {added} new warnings for {len(by_user)} users.")
