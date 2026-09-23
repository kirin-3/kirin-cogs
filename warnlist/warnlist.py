import re
from collections.abc import Callable

import discord
from redbot.core import Config, commands
from redbot.core.utils.views import SimpleMenu

PER_PAGE = 5
MAX_REASON = 550  # keeps 5 entries under the 4096-char embed description limit
DELETED_MOD = 0xDE1  # Red's placeholder for a moderator whose data was deleted
# yagpdbimport appends this to imported reasons: "... (YAGPDB, 2020-06-28, by name#0)"
YAG_SUFFIX = re.compile(r"\s*\(YAGPDB, \d{4}-\d{2}-\d{2}, by (?P<mod>.+)\)\s*$")
WARN_DM = (
    "You have been warned in the Unicornia Server for the following reason:\n"
    "{reason}\n\n"
    "**Further violations of server rules may result in channel restrictions, temporary mute, or permanent ban.**\n\n"
    "Use .mywarnings to see your warnings."
)


def format_warnings(warnings: dict, mod_name: Callable[[int], str | None]) -> list[str]:
    """Render Red warnings as embed text, newest first; #1 is the oldest.

    Each key is the snowflake of the warn message (imports build it from the YAGPDB date),
    so the key is the warning's date.
    """
    ordered = sorted(warnings.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)
    out = []
    for num, (key, w) in enumerate(ordered, 1):
        w = w if isinstance(w, dict) else {}
        reason = str(w.get("description") or "")
        mod_id = w.get("mod")
        mod = "Deleted moderator" if mod_id == DELETED_MOD else mod_name(mod_id) if isinstance(mod_id, int) else None
        tags = []
        if m := YAG_SUFFIX.search(reason):
            reason = reason[: m.start()]
            mod = mod or m["mod"]
            tags.append("YAGPDB")
        if isinstance(points := w.get("points"), int) and points:
            tags.append(f"{points} point{'s' if points != 1 else ''}")

        quoted = "\n".join(f"> {line}" for line in (reason.strip() or "No reason given.").splitlines())
        if len(quoted) > MAX_REASON:
            quoted = quoted[: MAX_REASON - 1] + "…"
        if key.isdigit():
            ts = ((int(key) >> 22) + discord.utils.DISCORD_EPOCH) // 1000
            when = f"<t:{ts}:D> (<t:{ts}:R>)"
        else:
            when = "unknown date"
        meta = " · ".join([f"Mod: {mod or f'Unknown ({mod_id})'}", *tags, f"ID `{key}`"])
        out.append(f"**#{num}** · {when}\n{quoted}\n{meta}")
    out.reverse()
    return out


class WarnList(commands.Cog):
    """Show warnings with their dates."""

    def __init__(self, bot, old_warnings: commands.Command | None):
        self.bot = bot
        self.old_warnings = old_warnings
        # Red's core Warnings cog storage; same defaults it registers.
        self.config = Config.get_conf(None, identifier=5757575755, cog_name="Warnings")
        self.config.register_member(total_points=0, status="", warnings={})

    async def cog_unload(self) -> None:
        # d.py has already removed our command; give Red's back if its cog is still the loaded one.
        if self.old_warnings and self.bot.get_cog("Warnings") is self.old_warnings.cog:
            self.bot.add_command(self.old_warnings)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx: commands.Context) -> None:
        """DM the member after Red's [p]warn saves a warning. Red's own DM is off via `warningset senddm false`."""
        if ctx.guild is None or ctx.command is None or ctx.command.qualified_name != "warn":
            return
        if ctx.command.cog_name != "Warnings":
            return
        member = next((a for a in ctx.args if isinstance(a, discord.Member)), None)
        if member is None:
            return
        warns = await self.config.member_from_ids(ctx.guild.id, member.id).warnings()
        warning = warns.get(str(ctx.message.id)) if isinstance(warns, dict) else None
        if not isinstance(warning, dict):
            return  # Red refused the warn (self-warn, unknown reason, ...)

        reason = str(warning.get("description") or "No reason given.")[:3800]  # embed limit is 4096
        embed = discord.Embed(description=WARN_DM.format(reason=reason), color=await ctx.embed_color())
        try:
            await member.send(embed=embed)
        except discord.HTTPException:
            await ctx.send(
                f"Warning saved, but I couldn't DM {member.mention} (DMs closed or they left).",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @commands.command(aliases=["warns"])
    @commands.guild_only()
    @commands.admin()
    async def warnings(self, ctx: commands.Context, user: discord.Member | discord.User) -> None:
        """List a user's warnings with their dates. Accepts an ID for users who left."""
        assert ctx.guild is not None
        guild = ctx.guild
        data = await self.config.member_from_ids(guild.id, user.id).all()
        warnings = data.get("warnings")

        def mod_name(mod_id: int) -> str | None:
            if member := guild.get_member(mod_id):
                return member.mention
            found = self.bot.get_user(mod_id)
            return str(found) if found else None

        entries = format_warnings(warnings, mod_name) if isinstance(warnings, dict) else []
        chunks = [entries[i : i + PER_PAGE] for i in range(0, len(entries), PER_PAGE)] or [
            ["*This user has no warnings.*"]
        ]
        color = await ctx.embed_color()
        pages = []
        for n, chunk in enumerate(chunks, 1):
            embed = discord.Embed(title="Warning history", description="\n\n".join(chunk), color=color)
            embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
            embed.set_footer(
                text=f"{len(entries)} warnings · {data.get('total_points', 0)} points · Page {n}/{len(chunks)}"
            )
            pages.append(embed)
        await SimpleMenu(pages).start(ctx)
