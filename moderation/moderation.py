import asyncio
import contextlib
import logging
import re
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta

import discord
from discord.ext import tasks
from redbot.core import Config, commands, modlog
from redbot.core.utils.views import SimpleMenu

log = logging.getLogger("red.kirin_cogs.moderation")

STAFF_ROLE_ID = 696020813299580940
MUTED_ROLE_ID = 686252873583165520
RULES_CHANNEL_ID = 684360255798509582  # unban reinvites point here
BAN_APPEAL_URL = "https://forms.gle/SdrjyV9ggi3hBQbh8"

PER_PAGE = 5
MAX_REASON = 550  # keeps 5 entries under the 4096-char embed description limit
DELETED_MOD = 0xDE1  # Red's placeholder for a moderator whose data was deleted
# yagpdbimport appends this to imported reasons: "... (YAGPDB, 2020-06-28, by name#0)"
YAG_SUFFIX = re.compile(r"\s*\(YAGPDB, \d{4}-\d{2}-\d{2}, by (?P<mod>.+)\)\s*$")
BAN_WARNING = "**Further violations of server rules may result in a permanent ban.**"

WARN_DM_TITLE = "\N{WARNING SIGN}\N{VARIATION SELECTOR-16} You have been warned"
WARN_DM = (
    "You have been warned in the **Unicornia Server** for the following reason:\n"
    "{reason}\n\n"
    "**Further violations of server rules may result in channel restrictions, temporary mute, or permanent ban.**"
)
WARN_DM_FOOTER = "Use .mywarnings to see your warnings."
MUTE_DM_TITLE = "\N{SPEAKER WITH CANCELLATION STROKE} You have been muted"
MUTE_DM = (
    "You have been muted in the **Unicornia Server** for the following reason:\n"
    "{reason}\n\n**Ends:** {ends}\n\n" + BAN_WARNING
)
UNMUTE_DM_TITLE = "\N{SPEAKER WITH THREE SOUND WAVES} You have been unmuted"
UNMUTE_DM = "Your mute in the **Unicornia Server** has ended and your roles have been given back."
KICK_DM_TITLE = "\N{WOMANS BOOTS} You have been kicked"
KICK_DM = "You have been kicked from the **Unicornia Server** for the following reason:\n{reason}\n\n" + BAN_WARNING
BAN_DM_TITLE = "\N{NO ENTRY} You have been banned"
BAN_DM = (
    "You have been banned from the **Unicornia Server** for the following reason:\n"
    "{reason}\n\n"
    f"If you believe your ban was unjustified you can appeal here: {BAN_APPEAL_URL}"
)
UNBAN_DM_TITLE = "\N{WHITE HEAVY CHECK MARK} You have been unbanned"
UNBAN_DM = (
    "You have been unbanned from the **Unicornia Server**. You can rejoin with this invite:\n{invite}\n\n"
    "The invite works once and expires in 24 hours."
)


def staff_or(**perms: bool):
    """Staff role, Red admins, bot owners, or members holding the Discord permissions for this action.

    Each command asks for its own permission, so e.g. Manage Roles alone can mute but not ban.
    """

    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage
        if not isinstance(ctx.author, discord.Member):
            return False
        if ctx.author.get_role(STAFF_ROLE_ID) is not None:
            return True
        if perms and all(getattr(ctx.author.guild_permissions, p) for p in perms):
            return True
        return await ctx.bot.is_owner(ctx.author) or await ctx.bot.is_admin(ctx.author)

    return commands.check(predicate)


def quote(text: str | None) -> str:
    return "\n".join(f"> {line}" for line in (text or "No reason given.").splitlines())[:3500]


def notice(guild: discord.Guild, title: str, body: str, color: discord.Color) -> discord.Embed:
    """The DM embed every action sends."""
    embed = discord.Embed(title=title, description=body, color=color, timestamp=discord.utils.utcnow())
    embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
    return embed


def split_roles(roles: Iterable[discord.Role]) -> tuple[list[discord.Role], list[int]]:
    """(roles the member keeps, ids of roles a mute strips). Bots can't remove managed or higher roles."""
    keep, strip = [], []
    for role in roles:
        if role.is_default() or role.id == MUTED_ROLE_ID:
            continue
        if role.is_assignable():
            strip.append(role.id)
        else:
            keep.append(role)
    return keep, strip


def unmuted_roles(current: Iterable[discord.Role], saved: list[discord.Role | None]) -> tuple[list[discord.Role], int]:
    """(roles after unmute, how many saved roles were deleted or moved above the bot since the mute)."""
    back = [r for r in saved if r is not None and r.is_assignable()]
    roles = {r for r in current if not r.is_default() and r.id != MUTED_ROLE_ID} | set(back)
    return list(roles), len(saved) - len(back)


def audit_reason(ctx: commands.Context, reason: str | None) -> str:
    return f"{ctx.author} ({ctx.author.id}): {reason or 'No reason given.'}"[:512]


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


class Moderation(commands.Cog):
    """Warnings, role-strip mutes, kicks, bans, and user info."""

    def __init__(self, bot, old_warnings: commands.Command | None):
        self.bot = bot
        self.old_warnings = old_warnings
        # mute = {"roles": [ids stripped by the mute], "until": unix time or None}
        self.config = Config.get_conf(self, identifier=0x6D6F6431, force_registration=True)
        self.config.register_member(mute=None)
        # ponytail: one lock per member ever muted, never freed; fine at mute volumes.
        self._locks: defaultdict[tuple[int, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        # Red's core Warnings cog storage; same defaults it registers.
        self.warnings_config = Config.get_conf(None, identifier=5757575755, cog_name="Warnings")
        self.warnings_config.register_member(total_points=0, status="", warnings={})

    async def cog_load(self) -> None:
        self.expire_mutes.start()

    async def cog_unload(self) -> None:
        self.expire_mutes.cancel()
        # d.py has already removed our command; give Red's back if its cog is still the loaded one.
        if self.old_warnings and self.bot.get_cog("Warnings") is self.old_warnings.cog:
            self.bot.add_command(self.old_warnings)

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Remove the user's saved mute roles in every guild."""
        for guild_id, members in (await self.config.all_members()).items():
            if user_id in members:
                await self.config.member_from_ids(guild_id, user_id).clear()

    # --- helpers -------------------------------------------------------------------------------

    @staticmethod
    async def _dm(user: discord.User | discord.Member, embed: discord.Embed) -> bool:
        try:
            await user.send(embed=embed)
        except discord.HTTPException:
            return False
        return True

    async def _case(
        self,
        guild: discord.Guild,
        action: str,
        user: discord.abc.User,
        moderator: discord.abc.User,
        reason: str | None,
        until: datetime | None = None,
    ) -> None:
        try:
            await modlog.create_case(self.bot, guild, discord.utils.utcnow(), action, user, moderator, reason, until)
        except Exception:
            log.exception("Could not create %s modlog case in %s", action, guild.id)

    @staticmethod
    def _hierarchy_error(ctx: commands.Context, target: discord.Member) -> str | None:
        guild, author = target.guild, ctx.author
        if target == author:
            return "You can't do that to yourself."
        if target == guild.owner:
            return "You can't do that to the server owner."
        if isinstance(author, discord.Member) and author != guild.owner and target.top_role >= author.top_role:
            return "They have the same or a higher role than you."
        if target.top_role >= guild.me.top_role:
            return "My highest role isn't above theirs."
        return None

    @staticmethod
    async def _find_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
        """Cached member, else ask Discord, so a cache gap never counts as "not in the server"."""
        if member := guild.get_member(user_id):
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.NotFound:
            return None

    def _lock(self, member: discord.Member) -> asyncio.Lock:
        """Serializes mute, unmute, and enforcement for one member so they never undo each other."""
        return self._locks[(member.guild.id, member.id)]

    async def _unmute(self, member: discord.Member, reason: str) -> int | None:
        """Give back the roles a mute stripped and remove Muted.

        Returns how many saved roles couldn't be given back, or None if the member isn't muted.
        """
        async with self._lock(member):
            member = member.guild.get_member(member.id) or member  # freshest cached roles
            group = self.config.member(member)
            record = await group.mute()
            muted_role = member.guild.get_role(MUTED_ROLE_ID)
            if not isinstance(record, dict) and (muted_role is None or muted_role not in member.roles):
                return None
            saved_ids = record.get("roles", []) if isinstance(record, dict) else []
            roles, skipped = unmuted_roles(member.roles, [member.guild.get_role(int(r)) for r in saved_ids])
            await member.edit(roles=roles, reason=reason[:512])
            await group.mute.clear()
            return skipped

    async def _enforce(self, member: discord.Member) -> None:
        """Keep a muted member at Muted plus the roles the bot can't remove.

        Roles added during a mute (Discord onboarding, linked roles, other bots, the rules button, staff)
        are taken off again and saved, so they come back on unmute instead of reopening channels now.
        A removed Muted role is put back: only `[p]unmute` or the timer ends a mute.
        """
        group = self.config.member(member)
        if not isinstance(await group.mute(), dict):
            return  # almost every role change is for someone who isn't muted; skip the lock
        async with self._lock(member):
            record = await group.mute()
            if not isinstance(record, dict) or (record.get("until") and record["until"] <= time.time()):
                return  # not muted, or expired and expire_mutes will unmute
            member = member.guild.get_member(member.id) or member  # freshest cached roles
            muted_role = member.guild.get_role(MUTED_ROLE_ID)
            keep, strip = split_roles(member.roles)
            if not strip and (muted_role is None or muted_role in member.roles):
                return
            record["roles"] = list(dict.fromkeys([*record.get("roles", []), *strip]))
            await group.mute.set(record)
            try:
                await member.edit(roles=[*keep, *([muted_role] if muted_role else [])], reason="Keeping mute in place")
            except discord.HTTPException:
                log.warning("Could not keep %s muted in %s", member.id, member.guild.id)

    @staticmethod
    def _ends(until: datetime | None) -> str:
        if until is None:
            return "when a moderator unmutes you"
        return f"{discord.utils.format_dt(until, 'F')} ({discord.utils.format_dt(until, 'R')})"

    # --- mutes ---------------------------------------------------------------------------------

    @tasks.loop(seconds=30)
    async def expire_mutes(self) -> None:
        now = time.time()
        for guild_id, members in (await self.config.all_members()).items():
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                continue
            for user_id, data in members.items():
                record = data.get("mute")
                if not isinstance(record, dict):
                    continue
                try:
                    if not record.get("until") or record["until"] > now:
                        # Still muted: also catches role changes made while the bot was offline.
                        if member := guild.get_member(user_id):
                            await self._enforce(member)
                        continue
                    member = await self._find_member(guild, user_id)
                    if member is None:  # left while muted; nothing to give back
                        await self.config.member_from_ids(guild_id, user_id).mute.clear()
                        continue
                    await self._unmute(member, "Mute expired")
                    await self._dm(member, notice(guild, UNMUTE_DM_TITLE, UNMUTE_DM, discord.Color.green()))
                    await self._case(guild, "sunmute", member, guild.me, "Mute expired")
                except Exception:
                    log.exception("Could not update the mute of %s in %s", user_id, guild_id)

    @expire_mutes.before_loop
    async def _before_expire_mutes(self) -> None:
        await self.bot.wait_until_red_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Leaving and rejoining must not clear a mute."""
        group = self.config.member(member)
        record = await group.mute()
        if isinstance(record, dict) and record.get("until") and record["until"] <= time.time():
            await group.mute.clear()  # ran out while they were away
            return
        await self._enforce(member)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.roles != after.roles:
            await self._enforce(after)

    @commands.command(usage="<member> [duration] [reason]")  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @staff_or(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def mute(
        self,
        ctx: commands.Context,
        member: discord.Member,
        duration: commands.TimedeltaConverter | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        """Take all of a member's roles and give them Muted. Their roles come back on unmute.

        `duration` is optional, e.g. `30m`, `2h`, `7d`, `1d12h`. Without it the mute lasts until `[p]unmute`.
        Muting someone who is already muted only changes when the mute ends.
        """
        assert ctx.guild is not None
        if error := self._hierarchy_error(ctx, member):
            await ctx.send(error)
            return
        muted_role = ctx.guild.get_role(MUTED_ROLE_ID)
        if muted_role is None or not muted_role.is_assignable():
            await ctx.send("The Muted role is missing or above my highest role.")
            return
        until = discord.utils.utcnow() + duration if isinstance(duration, timedelta) else None
        ends = f"until {discord.utils.format_dt(until, 'F')}" if until else "until someone unmutes them"
        group = self.config.member(member)
        async with self._lock(member):
            record = await group.mute()
            already = isinstance(record, dict)
            if isinstance(record, dict):
                record["until"] = until.timestamp() if until else None
                await group.mute.set(record)
            else:
                keep, strip = split_roles(member.roles)
                # Save first, so a crash between these two steps never loses the member's roles.
                await group.mute.set({"roles": strip, "until": until.timestamp() if until else None})
                try:
                    await member.edit(roles=[*keep, muted_role], reason=audit_reason(ctx, reason))
                except discord.HTTPException:
                    await group.mute.clear()
                    await ctx.send("I couldn't change their roles.")
                    return
        if already:
            await self._enforce(member)
            await ctx.send(f"**{member}** was already muted. They're now muted {ends}.")
            return

        notes = ""
        if member.voice is not None and member.voice.channel is not None:
            try:
                await member.move_to(None, reason=audit_reason(ctx, reason))
            except discord.HTTPException:
                notes += " They're in voice and I couldn't disconnect them (I need Move Members)."
        body = MUTE_DM.format(reason=quote(reason), ends=self._ends(until))
        if not await self._dm(member, notice(ctx.guild, MUTE_DM_TITLE, body, discord.Color.dark_orange())):
            notes += " I couldn't DM them."
        await self._case(ctx.guild, "smute", member, ctx.author, reason, until)
        await ctx.send(f"\N{SPEAKER WITH CANCELLATION STROKE} Muted **{member}** {ends}.{notes}")

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @staff_or(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unmute(
        self, ctx: commands.Context, user: discord.Member | discord.User, *, reason: str | None = None
    ) -> None:
        """Remove Muted and give back the roles the mute took. Accepts an ID for users who left."""
        assert ctx.guild is not None
        member = await self._find_member(ctx.guild, user.id)
        if member is None:
            group = self.config.member_from_ids(ctx.guild.id, user.id)
            if not isinstance(await group.mute(), dict):
                await ctx.send(f"**{user}** isn't muted.")
                return
            await group.mute.clear()
            await self._case(ctx.guild, "sunmute", user, ctx.author, reason)
            await ctx.send(
                f"Lifted **{user}**'s mute. They aren't in the server, so they won't be muted if they rejoin."
            )
            return
        try:
            skipped = await self._unmute(member, audit_reason(ctx, reason))
        except discord.HTTPException:
            await ctx.send("I couldn't change their roles.")
            return
        if skipped is None:
            await ctx.send(f"**{member}** isn't muted.")
            return
        dm_ok = await self._dm(member, notice(ctx.guild, UNMUTE_DM_TITLE, UNMUTE_DM, discord.Color.green()))
        await self._case(ctx.guild, "sunmute", member, ctx.author, reason)
        msg = f"\N{SPEAKER WITH THREE SOUND WAVES} Unmuted **{member}**."
        if skipped:
            msg += f" {skipped} saved role(s) were deleted or are above me now, so I couldn't give those back."
        await ctx.send(msg + ("" if dm_ok else " I couldn't DM them."))

    # --- kicks and bans ------------------------------------------------------------------------

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @staff_or(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        """DM a member, then kick them."""
        assert ctx.guild is not None
        if error := self._hierarchy_error(ctx, member):
            await ctx.send(error)
            return
        body = KICK_DM.format(reason=quote(reason))
        dm_ok = await self._dm(member, notice(ctx.guild, KICK_DM_TITLE, body, discord.Color.red()))
        try:
            await member.kick(reason=audit_reason(ctx, reason))
        except discord.HTTPException:
            await ctx.send("I couldn't kick them.")
            return
        await self._case(ctx.guild, "kick", member, ctx.author, reason)
        await ctx.send(f"\N{WOMANS BOOTS} Kicked **{member}**." + ("" if dm_ok else " I couldn't DM them."))

    @commands.command(usage="<user> [days] [reason]")  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @staff_or(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(
        self,
        ctx: commands.Context,
        user: discord.Member | discord.User,
        days: commands.Range[int, 0, 7] | None = None,
        *,
        reason: str | None = None,
    ) -> None:
        """DM a user, then ban them. Works with an ID for users who aren't in the server.

        `days` (0-7) deletes that many days of their messages. Leave it out to delete none.
        """
        assert ctx.guild is not None
        member = await self._find_member(ctx.guild, user.id)
        dm_ok = False
        if member is not None:
            if error := self._hierarchy_error(ctx, member):
                await ctx.send(error)
                return
            body = BAN_DM.format(reason=quote(reason))
            dm_ok = await self._dm(member, notice(ctx.guild, BAN_DM_TITLE, body, discord.Color.dark_red()))
        try:
            await ctx.guild.ban(user, reason=audit_reason(ctx, reason), delete_message_seconds=(days or 0) * 86400)
        except discord.HTTPException:
            await ctx.send("I couldn't ban them.")
            return
        await self.config.member_from_ids(ctx.guild.id, user.id).mute.clear()  # a ban replaces any mute
        await self._case(ctx.guild, "ban" if member else "hackban", user, ctx.author, reason)
        note = "" if dm_ok or member is None else " I couldn't DM them."
        await ctx.send(f"\N{NO ENTRY} Banned **{user}**.{note}")

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @staff_or(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(
        self, ctx: commands.Context, user_id: commands.RawUserIdConverter, *, reason: str | None = None
    ) -> None:
        """Unban a user by ID and send them a one-use invite to the rules channel."""
        assert ctx.guild is not None
        try:
            ban = await ctx.guild.fetch_ban(discord.Object(user_id))  # pyright: ignore[reportArgumentType]
        except discord.NotFound:
            await ctx.send("That user isn't banned.")
            return
        try:
            await ctx.guild.unban(ban.user, reason=audit_reason(ctx, reason))
        except discord.HTTPException:
            await ctx.send("I couldn't unban them.")
            return
        await self._case(ctx.guild, "unban", ban.user, ctx.author, reason)

        channel = ctx.guild.get_channel(RULES_CHANNEL_ID)
        invite = None
        if isinstance(channel, discord.TextChannel):
            with contextlib.suppress(discord.HTTPException):
                invite = await channel.create_invite(max_age=86400, max_uses=1, unique=True, reason="Unban reinvite")
        done = f"\N{WHITE HEAVY CHECK MARK} Unbanned **{ban.user}**."
        if invite is None:
            await ctx.send(done + " I couldn't create an invite for them.")
            return
        body = UNBAN_DM.format(invite=invite.url)
        if await self._dm(ban.user, notice(ctx.guild, UNBAN_DM_TITLE, body, discord.Color.green())):
            await ctx.send(done + " I DMed them an invite.")
        else:
            # Bots can only DM people they share a server with, which a banned user usually doesn't.
            await ctx.send(done + f" I couldn't DM them, so send them this one-use invite yourself: {invite.url}")

    # --- info ----------------------------------------------------------------------------------

    @commands.command()
    @commands.guild_only()
    @staff_or()
    async def userinfo(self, ctx: commands.Context, user: discord.Member | discord.User | None = None) -> None:
        """Account age, join date, roles, warning count, and mute status."""
        assert ctx.guild is not None
        user = user or ctx.author
        member = ctx.guild.get_member(user.id)
        warns = await self.warnings_config.member_from_ids(ctx.guild.id, user.id).warnings()
        record = await self.config.member_from_ids(ctx.guild.id, user.id).mute()

        if isinstance(record, dict):
            until = record.get("until")
            muted = f"Yes, ends <t:{int(until)}:R>" if until else "Yes, no end time"
        elif member is not None and member.get_role(MUTED_ROLE_ID) is not None:
            muted = "Yes (not muted by this bot)"
        else:
            muted = "No"
        color = member.color if member is not None and member.color.value else await ctx.embed_color()
        embed = discord.Embed(color=color)
        embed.set_author(name=f"{user} ({user.id})", icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)
        created = user.created_at
        embed.add_field(
            name="Account created",
            value=f"{discord.utils.format_dt(created, 'D')} ({discord.utils.format_dt(created, 'R')})",
        )
        if member is not None and member.joined_at is not None:
            joined = member.joined_at
            joined_text = f"{discord.utils.format_dt(joined, 'D')} ({discord.utils.format_dt(joined, 'R')})"
        else:
            joined_text = "Not in the server"
        embed.add_field(name="Joined server", value=joined_text)
        embed.add_field(name="Warnings", value=str(len(warns) if isinstance(warns, dict) else 0))
        embed.add_field(name="Muted", value=muted)
        if member is not None:
            roles = " ".join(r.mention for r in reversed(member.roles) if not r.is_default()) or "None"
            if len(roles) > 1024:
                roles = roles[:1000].rsplit(" ", 1)[0] + " …"
            embed.add_field(name="Roles", value=roles, inline=False)
        await ctx.send(embed=embed)

    # --- warnings ------------------------------------------------------------------------------

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
        warns = await self.warnings_config.member_from_ids(ctx.guild.id, member.id).warnings()
        warning = warns.get(str(ctx.message.id)) if isinstance(warns, dict) else None
        if not isinstance(warning, dict):
            return  # Red refused the warn (self-warn, unknown reason, ...)

        reason = str(warning.get("description") or "No reason given.")
        embed = notice(ctx.guild, WARN_DM_TITLE, WARN_DM.format(reason=quote(reason)), discord.Color.orange())
        embed.timestamp = ctx.message.created_at
        embed.set_footer(text=WARN_DM_FOOTER)
        if not await self._dm(member, embed):
            await ctx.send(
                f"Warning saved, but I couldn't DM {member.mention} (DMs closed or they left).",
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @commands.command(aliases=["warns"])
    @commands.guild_only()
    @staff_or()
    async def warnings(self, ctx: commands.Context, user: discord.Member | discord.User) -> None:
        """List a user's warnings with their dates. Accepts an ID for users who left."""
        assert ctx.guild is not None
        guild = ctx.guild
        data = await self.warnings_config.member_from_ids(guild.id, user.id).all()
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
