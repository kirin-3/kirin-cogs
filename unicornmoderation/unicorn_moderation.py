import functools
import logging
from typing import Literal

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.i18n import Translator, cog_i18n

from .image_generator import generate_citation

log = logging.getLogger("red.kirin_cogs.unicornmoderation")
_ = Translator("UnicornModeration", __file__)


@cog_i18n(_)
class UnicornModeration(commands.Cog):
    """
    Moderation cog with a papers please theme.
    """

    __author__ = "Vertyco"
    __version__ = "0.0.1"

    def format_help_for_context(self, ctx: commands.Context) -> str:
        helpcmd = super().format_help_for_context(ctx)
        info = f"{helpcmd}\nCog Version: {self.__version__}\nAuthor: {self.__author__}\n"
        return info

    async def red_delete_data_for_user(  # type: ignore[override]
        self,
        *,
        requester: Literal["discord_deleted_user", "owner", "user", "user_strict"],
        user_id: int,
    ) -> None:
        """Delete all guild-scoped warning records for the user."""
        for guild_id, members in (await self.config.all_members()).items():
            if isinstance(members, dict) and (user_id in members or str(user_id) in members):
                await self.config.member_from_ids(guild_id, user_id).clear()

    def __init__(self, bot: Red):
        self.bot: Red = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_member = {"warnings": []}
        self.config.register_member(**default_member)

    async def _log_action(self, action: str, member: discord.Member, reason: str) -> None:
        """Generate and send the citation image to the log channel."""
        log_channel = self.bot.get_channel(694857480307474432)
        if not log_channel or not isinstance(log_channel, discord.abc.Messageable):
            return

        task = functools.partial(generate_citation, action, member.display_name, reason)
        image_buffer = await self.bot.loop.run_in_executor(None, task)
        file = discord.File(image_buffer, filename="citation.png")
        await log_channel.send(file=file)

    @commands.command()  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        """Ban a member and delete their messages from the last hour."""
        assert ctx.guild is not None
        if reason is None:
            reason = f"Banned by {ctx.author.name}"
        await member.ban(delete_message_seconds=3600, reason=reason)
        await self._log_action("Ban", member, reason)
        await ctx.send(f"Banned {member.mention} for: {reason}")

    @commands.command()  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        """Kick a member from the server."""
        assert ctx.guild is not None
        if reason is None:
            reason = f"Kicked by {ctx.author.name}"
        await member.kick(reason=reason)
        await self._log_action("Kick", member, reason)
        await ctx.send(f"Kicked {member.mention} for: {reason}")

    @commands.command()  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def mute(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        """Mute a member."""
        assert ctx.guild is not None
        muted_role = ctx.guild.get_role(686252873583165520)
        if not muted_role:
            await ctx.send("The muted role could not be found.")
            return
        if reason is None:
            reason = f"Muted by {ctx.author.name}"
        await member.add_roles(muted_role, reason=reason)
        await self._log_action("Mute", member, reason)
        await ctx.send(f"Muted {member.mention} for: {reason}")

    @commands.command()  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def unmute(self, ctx: commands.Context, member: discord.Member, *, reason: str | None = None) -> None:
        """Unmute a member."""
        assert ctx.guild is not None
        muted_role = ctx.guild.get_role(686252873583165520)
        if not muted_role:
            await ctx.send("The muted role could not be found.")
            return
        if reason is None:
            reason = f"Unmuted by {ctx.author.name}"
        await member.remove_roles(muted_role, reason=reason)
        await self._log_action("Unmute", member, reason)
        await ctx.send(f"Unmuted {member.mention}")

    @commands.command()  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str) -> None:
        """Warn a user."""
        warning = {"moderator": ctx.author.id, "reason": reason, "timestamp": ctx.message.created_at.isoformat()}
        async with self.config.member(member).warnings() as warnings:
            warnings.append(warning)
        await self._log_action("Warning", member, reason)
        await ctx.send(f"Warned {member.mention} for: {reason}")

    @commands.command()  # type: ignore[arg-type]
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    async def warnings(self, ctx: commands.Context, member: discord.Member) -> None:
        """Check a user's warnings."""
        assert ctx.guild is not None
        warnings = await self.config.member(member).warnings()
        if not warnings:
            await ctx.send(f"{member.mention} has no warnings.")
            return

        embed = discord.Embed(title=f"Warnings for {member.display_name}", color=await ctx.embed_color())
        for i, warning in enumerate(warnings, 1):
            moderator = ctx.guild.get_member(warning["moderator"])
            moderator_name = moderator.display_name if moderator else "Unknown Moderator"
            embed.add_field(
                name=f"Warning {i}",
                value=f"**Moderator:** {moderator_name}\n**Reason:** {warning['reason']}\n**Date:** {warning['timestamp']}",
                inline=False,
            )
        await ctx.send(embed=embed)
