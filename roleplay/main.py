"""Main module for roleplay bot"""

import asyncio
import logging
from collections import Counter
from io import BufferedIOBase
from math import ceil
from pathlib import Path
from time import monotonic
from typing import Annotated

import discord
from redbot.core import Config, app_commands, commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import humanize_list, inline

from . import __version__, consent, const
from .actions import PAIRINGS, POOLS, Action, ActionManager, pick_image, pool_of
from .dashboard import SettingsDashboard
from .gifs import PAGE_SIZE, GifVotes, gif_info, gifs_of, page_of
from .help import Help
from .settings import Settings
from .tally import Tally, member_stats, summary, top_pairs
from .unicornia import strings
from .user_settings import USER_SETTINGS
from .views import request_consent

# The settings the member site may change; the user lists stay command-only
WEB_TOGGLES = ("selective", "public", "servant", "untracked")


class PairingConverter(commands.Converter[str]):
    """Converter for a pairing word (mlw, wlm, wlw or mlm) in any case. Used as an
    optional argument, anything else is left for the next argument. A class rather
    than a function so hybrid commands can use it for the slash option too."""

    async def convert(self, ctx: commands.Context, argument: str) -> str:  # pyright: ignore[reportIncompatibleMethodOverride]
        pairing = argument.lower()
        if pairing not in PAIRINGS:
            raise commands.BadArgument(f"{argument} is not a pairing.")
        return pairing


Pairing = Annotated[str, PairingConverter]
PAIRING_CHOICES = [app_commands.Choice(name=pairing, value=pairing) for pairing in PAIRINGS]


class Roleplay(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot

        self.logger = logging.getLogger("red.kirin_cogs.roleplay")
        self.logger.setLevel(const.LOGGER_LEVEL)

        self.action_manager = ActionManager()
        self.helper = Help(self.action_manager)
        self.user_settings = Settings(bot, self)
        # The Settings config above keeps member settings; this one keeps the action counts
        self.config = Config.get_conf(self, identifier=const.COG_IDENTIFIER, force_registration=True)
        self.tally = Tally(self.config, self.is_untracked)
        self.gif_votes = GifVotes(self.config)
        # When each member last had a gif forwarded, by monotonic time. Lost on reload, which is fine.
        self._gif_sent: dict[int, float] = {}

        # action commands are added to the bot directly, see create_action_command()
        self.action_commands: list[commands.Command] = []

        self.create_action_commands()

        self.logger.info("-" * 32)
        self.logger.info(f"{self.__class__.__name__} v({__version__}) initialized!")
        self.logger.info("-" * 32)

    @property
    def images_path(self) -> Path:
        """The action images, one folder per action. Read each time an action is used."""
        return cog_data_path(self) / "images"

    async def cog_unload(self):
        # the bot only removes the cog's own commands when it's unloaded, so the action
        # commands added to it directly have to be removed here or reloading will fail
        for command in self.action_commands:
            if self.bot.all_commands.get(command.name) is command:
                self.bot.remove_command(command.name)

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Remove the user's roleplay settings, their ID from every other member's lists, their action counts and gif votes."""
        await self.user_settings.users_manager.delete_user_data(user_id)
        await self.tally.forget(user_id)
        await self.gif_votes.forget(user_id)

    async def is_untracked(self, user_id: int) -> bool:
        return bool(await self.user_settings.config.user_from_id(user_id).untracked())

    async def setting_changed(self, user_id: int, key: str, value: bool) -> None:
        """Turning Untracked on deletes what was counted for the member."""
        if key == "untracked" and value:
            await self.tally.forget(user_id)

    # --- For the member site ---

    async def settings_for(self, user_id: int) -> dict[str, dict]:
        """A member's own settings, keyed like USER_SETTINGS, each with its label,
        description, emoji and value (a bool, or a list of user IDs)."""
        data = await self.user_settings.config.user_from_id(user_id).all()
        return {
            key: {
                "label": values["label"],
                "description": values["description"],
                "emoji": values["emoji"],
                "value": data.get(key, values["default"]),
            }
            for key, values in USER_SETTINGS.items()
        }

    async def set_toggle(self, user_id: int, key: str, value: bool) -> None:
        """Turn one of the on/off settings on or off. The lists are managed in Discord only."""
        if key not in WEB_TOGGLES:
            raise ValueError(f"{key!r} can't be changed here.")
        await self.user_settings.config.user_from_id(user_id).get_attr(key).set(bool(value))
        await self.setting_changed(user_id, key, bool(value))

    async def stats_for(self, user_id: int) -> dict:
        """A member's own counts for the member site: totals, top actions and top partners (as user IDs)."""
        if await self.is_untracked(user_id):
            return {"untracked": True}
        given, received, partners = member_stats(await self.tally.pairs(), user_id)
        return {
            "untracked": False,
            "given": given.most_common(5),
            "given_total": given.total(),
            "received": received.most_common(5),
            "received_total": received.total(),
            "partners": partners.most_common(5),
        }

    async def action_counts(self, user_id: int) -> Counter[str] | None:
        """Every action the member gave or got, added up, for other cogs; None when they're untracked."""
        if await self.is_untracked(user_id):
            return None
        given, received, _ = member_stats(await self.tally.pairs(), user_id)
        return given + received

    async def top_pairs(self, limit: int = 10) -> list[dict]:
        """The busiest pairs on the server for the member site, as user IDs, with their top actions."""
        return [
            {"a": a, "b": b, "total": counts.total(), "actions": counts.most_common(3)}
            for a, b, counts in top_pairs(await self.tally.pairs(), limit)
        ]

    # --- Gifs, for the member and staff sites ---

    async def _gifs(self, action: str) -> dict[str, Path]:
        """An action's images by filename, as the folder is right now. LookupError if it isn't an action."""
        if action not in self.action_manager.list():
            raise LookupError(action)
        return await asyncio.to_thread(gifs_of, self.images_path / action)

    async def gif_actions(self) -> list[dict]:
        """Every action with the number of gifs it has, by name: ``[{"name", "count"}]``."""
        return [{"name": name, "count": len(await self._gifs(name))} for name in self.action_manager.list()]

    async def gif_page(self, action: str, pool: str, user_id: int, page: int) -> dict:
        """One page of an action's pool, by filename: ``{"gifs": [{"name", "mine"}], "page", "pages"}``.

        ``mine`` is the member's own vote on the gif (1, -1 or 0). Raises LookupError for an unknown action or pool.
        """
        if pool not in POOLS:
            raise LookupError(pool)
        gifs = await self._gifs(action)
        names = [name for name, path in gifs.items() if pool_of(path) == pool]
        shown, page, pages = page_of(names, page, PAGE_SIZE)
        mine = await self.gif_votes.mine(user_id, action, shown)
        return {"gifs": [{"name": name, "mine": mine.get(name, 0)} for name in shown], "page": page, "pages": pages}

    async def gif_path(self, action: str, name: str) -> Path | None:
        """The file of a gif, or None if the action or the name isn't in the folder."""
        try:
            return (await self._gifs(action)).get(name)
        except LookupError:
            return None

    async def gif_vote(self, user_id: int, action: str, name: str, value: int) -> None:
        """Set the member's vote on a gif: 1 (up), -1 (down) or 0 (none). LookupError unless the gif exists."""
        if name not in await self._gifs(action):
            raise LookupError(name)
        await self.gif_votes.set(user_id, action, name, value)

    async def gif_vote_totals(self) -> list[dict]:
        """Every gif with a vote and a file, lowest score first: ``[{"action", "name", "up", "down"}]``."""
        rows = []
        present: dict[str, dict[str, Path]] = {}
        for (action, name), (up, down) in (await self.gif_votes.totals()).items():
            if action not in present:
                try:
                    present[action] = await self._gifs(action)
                except LookupError:
                    present[action] = {}
            if name in present[action]:
                rows.append({"action": action, "name": name, "up": up, "down": down})
        rows.sort(key=lambda row: (row["up"] - row["down"], -(row["up"] + row["down"]), row["action"], row["name"]))
        return rows

    def can_submit_gif(self, member: discord.Member) -> bool:
        """Whether the member may send in a gif right now, from the roles they hold."""
        return any(role.id in const.GIF_UPLOAD_ROLES for role in member.roles)

    async def submit_gif(self, member: discord.Member, action: str, fp: BufferedIOBase) -> None:
        """Post a member's gif in the review channel for staff. The bot keeps no copy and writes nothing to the images.

        Raises ValueError with a message for the member if the gif is refused.
        """
        if not self.can_submit_gif(member):
            raise ValueError("Only supporters and Level 90+ members can send in gifs.")
        now = monotonic()
        wait = self._gif_sent.get(member.id, now - const.GIF_SUBMIT_COOLDOWN) + const.GIF_SUBMIT_COOLDOWN - now
        if wait > 0:
            raise ValueError(f"You sent a gif a moment ago. Wait {ceil(wait)} more seconds to send another.")
        # Taken now so two uploads at once can't both get past the check; given back if this one is refused
        self._gif_sent[member.id] = now
        try:
            await self._forward_gif(member, action, fp)
        except Exception:
            self._gif_sent.pop(member.id, None)
            raise
        self._gif_sent = {user_id: at for user_id, at in self._gif_sent.items() if now - at < const.GIF_SUBMIT_COOLDOWN}

    async def _forward_gif(self, member: discord.Member, action_name: str, fp: BufferedIOBase) -> None:
        action = self.action_manager.get(action_name)
        if action is None:
            raise ValueError("Choose one of the roleplay actions.")
        is_gif, size = await asyncio.to_thread(gif_info, fp)
        if not is_gif:
            raise ValueError("Only GIF files are accepted.")
        channel = self.bot.get_channel(const.GIF_REVIEW_CHANNEL)
        limit = (channel.guild if isinstance(channel, discord.TextChannel) else member.guild).filesize_limit
        if size > limit:
            raise ValueError(f"That gif is too big. Discord allows files up to {limit // 1024 // 1024} MB.")
        unavailable = ValueError("Gif uploads are unavailable right now. Try again later.")
        if not isinstance(channel, discord.TextChannel):
            self.logger.warning(f"The gif review channel {const.GIF_REVIEW_CHANNEL} can't be found.")
            raise unavailable
        permissions = channel.permissions_for(channel.guild.me)
        if not (permissions.view_channel and permissions.send_messages and permissions.attach_files):
            self.logger.warning(f"The bot can't send files in the gif review channel {channel.id}.")
            raise unavailable
        try:
            await channel.send(
                f"**{action.name}** gif from {member.mention} (`{member.id}`)",
                file=discord.File(fp, filename=f"{action.name}.gif"),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            self.logger.exception(f"Sending a {action.name} gif to the review channel failed.")
            raise unavailable from None

    @commands.hybrid_command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True)
    async def rpstats(
        self, ctx: commands.GuildContext, member: discord.Member | None = None, other: discord.Member | None = None
    ) -> None:
        """Roleplay action counts: yours, a member's, or between two members."""
        members = [m for m in (member or ctx.author, other) if m is not None]
        for m in members:
            if await self.is_untracked(m.id):
                await ctx.send(f"**{m.display_name}** keeps their roleplay stats private.")
                return
        pairs = await self.tally.pairs()

        if len(members) == 2:
            a, b = members
            ab, ba = pairs.get((a.id, b.id)), pairs.get((b.id, a.id))
            total = (ab.total() if ab else 0) + (ba.total() if ba else 0)
            embed = discord.Embed(
                title=f"Roleplay stats: {a.display_name} & {b.display_name}",
                description=f"**{total:,}** actions between them.",
                color=const.EMBED_COLOR,
            )
            embed.add_field(name=f"{a.display_name} → {b.display_name}", value=summary(ab, 5) if ab else "Nothing yet")
            embed.add_field(name=f"{b.display_name} → {a.display_name}", value=summary(ba, 5) if ba else "Nothing yet")
            await ctx.send(embed=embed)
            return

        (target,) = members
        given, received, partners = member_stats(pairs, target.id)
        if not (given or received):
            await ctx.send(f"**{target.display_name}** hasn't done or received any roleplay actions yet.")
            return
        embed = discord.Embed(title=f"Roleplay stats: {target.display_name}", color=const.EMBED_COLOR)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name=f"Given ({given.total():,})", value=summary(given, 5) or "Nothing yet", inline=False)
        embed.add_field(
            name=f"Received ({received.total():,})", value=summary(received, 5) or "Nothing yet", inline=False
        )
        top = partners.most_common(5)
        names = await self.user_settings.users_manager.display_names([user_id for user_id, _ in top])
        embed.add_field(
            name="Favourite partners",
            value="\n".join(f"{name}: **{times:,}**" for name, (_, times) in zip(names, top, strict=True)),
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.group(invoke_without_command=True)
    async def roleplay(self, ctx: commands.Context):
        """Parent command for roleplay settings."""
        if ctx.invoked_subcommand is None:
            return await self.helper.roleplay(ctx)

    @roleplay.group(invoke_without_command=True)
    @commands.admin()
    async def admin(self, ctx: commands.Context):
        """Parent command for roleplay admin settings."""
        if ctx.invoked_subcommand is None:
            return

    @admin.group(aliases=["logger"], invoke_without_command=True)
    async def logger_settings(self, ctx: commands.Context):
        """Logger settings for roleplay."""
        if ctx.invoked_subcommand is None:
            level_name = logging.getLevelName(self.logger.level)
            msg = f'Logger level is currently set to "{level_name}".'
            return await ctx.send(msg)

    @logger_settings.command(aliases=["level", "setlevel"])
    async def logger_set_level(self, ctx: commands.Context, level_name: str):
        """Set logger level."""
        level = logging.getLevelNamesMapping().get(level_name.upper())
        if level is None:
            msg = f"{level_name.upper()} is not a valid logger level!\n({', '.join(logging.getLevelNamesMapping())})"
            self.logger.debug(msg)
            return await ctx.send(msg)

        self.logger.setLevel(level)
        msg = f'Logger level set to "{level_name}".'
        self.logger.info(msg)
        return await ctx.send(msg)

    @roleplay.command(aliases=["help"])
    async def roleplay_help(self, ctx: commands.Context):
        """Subcommand for roleplay help"""
        self.logger.debug("Default help for `roleplay` command intercepted.")
        return await self.helper.roleplay(ctx)

    @roleplay.group(invoke_without_command=True)
    async def settings(self, ctx: commands.Context, member: discord.Member | None = None):
        """Parent command for roleplay settings."""
        if ctx.invoked_subcommand is None:
            return await self.user_settings.manage_settings(ctx, member=member)

    @settings.command(aliases=["help"])
    async def settings_help(self, ctx: commands.Context):
        self.logger.debug("Default help for `roleplay settings` command intercepted.")
        return await self.helper.settings(ctx)

    @settings.group(name="actions", aliases=["always"], invoke_without_command=True)
    async def consented_actions(self, ctx: commands.Context):
        """Actions you consent to from anyone (except blocked members), without being asked."""
        if ctx.invoked_subcommand is None:
            names = await self.user_settings.consented_actions(ctx.author)
            if not names:
                await ctx.send(f"{ctx.author.display_name} has no always allowed actions.")
            else:
                await ctx.send(
                    f"Always allowed actions for {ctx.author.display_name}: {humanize_list([inline(n) for n in names])}."
                )

    @consented_actions.command(name="add")
    async def consented_actions_add(self, ctx: commands.Context, *action_names: str):
        """Always allow these actions, e.g. `hug pet`."""
        await self.change_consented_actions(ctx, action_names, add=True)

    @consented_actions.command(name="remove")
    async def consented_actions_remove(self, ctx: commands.Context, *action_names: str):
        """Ask again before these actions."""
        await self.change_consented_actions(ctx, action_names, add=False)

    async def change_consented_actions(self, ctx: commands.Context, action_names: tuple[str, ...], add: bool) -> None:
        actions = [self.action_manager.get(name.lower()) for name in action_names]
        unknown = [name for name, action in zip(action_names, actions, strict=True) if action is None]
        if not action_names or unknown:
            names = humanize_list([inline(name) for name in self.action_manager.list()])
            await ctx.send(f"Name one or more roleplay actions: {names}.")
            return
        changed = {action.name for action in actions if action is not None}
        current = set(await self.user_settings.consented_actions(ctx.author))
        names = sorted(current | changed if add else current - changed)
        await self.user_settings.config.user(ctx.author).consented_actions.set(names)
        await ctx.send(
            f"Always allowed actions for {ctx.author.display_name}: {humanize_list([inline(n) for n in names])}."
            if names
            else f"{ctx.author.display_name} has no always allowed actions."
        )

    # A prefix command can't answer ephemerally, so [p]roleplay settings shows a button.
    # This slash command opens the settings dashboard straight away, visible only to the member.
    roleplay_slash = app_commands.Group(name="roleplay", description="Roleplay commands.")

    @roleplay_slash.command(name="settings", description="Show your roleplay settings (only you can see them).")
    async def settings_slash(self, interaction: discord.Interaction):
        embed, dashboard = await SettingsDashboard.open(self.user_settings, interaction.user, interaction.user.id)
        dashboard.interaction = interaction
        await interaction.response.send_message(embed=embed, view=dashboard, ephemeral=True)

    def create_action_commands(self):
        """Factory to create command methods roleplay action"""
        for action in self.action_manager.actions:
            self.create_action_command(action.name, action.help, action.aliases)

    def create_action_command(self, action_name: str, help_text: str, aliases: list[str]) -> None:
        """Creates a new command for a roleplay action

        Args:
            action_name (str): The name of the command.
            help_text (str): The help text for the command.
            aliases (List[str]): A list of aliases for the command.
        """

        # method needs to be defined here so it can be changed for each action
        async def command_method(
            ctx: commands.GuildContext,
            pairing: Pairing | None = None,
            *,
            target_member: discord.Member | None = None,
        ):
            """Executes the specified action for the given member.

            Args:
                ctx (commands.GuildContext): The context of the command invocation.
                pairing (Optional, str): Only use images with this pairing tag.
                target_member (Optional, discord.Member): The member to perform the action on.
            """
            invoker_member = ctx.author

            # if a target_member wasn't supplied, the user is requesting the bot/default
            # member perform the action on themselves
            if not target_member or target_member.id == ctx.author.id:
                invoker_member = self.user_settings.users_manager.get_default_member(ctx)
                target_member = ctx.author

            # attempt an interaction
            result = await self.interaction(
                ctx,
                action_name,
                invoker_member,
                target_member,
                interaction_type=const.InteractionType.ACTIVE,
                pairing=pairing,
            )

            # if the interaction wasn't successful, reset the cooldown for this command
            if result is not True:
                self.reset_cooldown(ctx, action_name)

            return result

        command_method.__name__ = action_name
        command_method.__doc__ = help_text

        # include capitalized version of command and aliases
        all_aliases = [*aliases, *(a.capitalize() for a in aliases), action_name.capitalize()]

        app_commands.describe(pairing="Only use gifs with this pairing", target_member="Who to do it to")(
            command_method
        )
        app_commands.rename(target_member="member")(command_method)
        app_commands.choices(pairing=PAIRING_CHOICES)(command_method)
        command = commands.hybrid_command(name=action_name, aliases=all_aliases)(command_method)
        command = commands.cooldown(const.COOLDOWN_RATE, const.COOLDOWN_TIME, commands.BucketType.channel)(command)
        command = commands.bot_has_permissions(embed_links=True, attach_files=True)(command)
        command = commands.guild_only()(command)

        # I don't know why, but this particular configuration makes the command
        # executable both from the global bot scope (&hug) as well as under roleplay
        # group (&roleplay hug) but the individual commands do not show up in the redbot
        # help menu under "no category"
        setattr(self, action_name, command)

        # a copy of this command can still be registered from before cog_unload()
        # cleaned up after itself. Only remove it if it came from this cog's code, so
        # another cog's command with the same name is left alone
        existing = self.bot.all_commands.get(action_name)
        if existing is not None and existing.cog is None and existing.module == command.module:
            self.bot.remove_command(action_name)

        self.bot.add_command(command)
        self.action_commands.append(command)
        # Add the command to the roleplay group
        self.roleplay.add_command(command)

    @commands.hybrid_command(aliases=["askfor", "get", "giveme", "gimme", "request"])  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.bot_has_permissions(embed_links=True, attach_files=True)
    @app_commands.describe(
        action_name="The action to ask for",
        pairing="Only use gifs with this pairing",
        target_member="Who to ask",
    )
    @app_commands.rename(action_name="action", target_member="member")
    @app_commands.choices(pairing=PAIRING_CHOICES)
    async def ask(
        self,
        ctx: commands.GuildContext,
        action_name: str,
        pairing: Pairing | None = None,
        target_member: discord.Member | None = None,
    ):
        """Ask another member to perform an action on you

        This command serves as a wrapper for .interaction(). It allows a member to ask
        another member to perform an action on themselves.

        Args:
            ctx (commands.GuildContext): The context of the command invocation.
            action_name (str): The name of the roleplay action.
            pairing (Optional, str): Only use images with this pairing tag.
            target_member (Optional, discord.Member): The member to perform this action on.
        """
        invoker_member = ctx.author

        # if a target_member wasn't supplied, the user is requesting the bot/default
        # member perform the action on them
        if not target_member or target_member.id == ctx.author.id:
            target_member = self.user_settings.users_manager.get_default_member(ctx)
            self.logger.debug(f"Action performed by member on themselves. Substituting {target_member}.")

        action = self.action_manager.get(action_name)
        if action is None:
            names = humanize_list([inline(name) for name in self.action_manager.list()])
            await ctx.send(f"{inline(action_name)} isn't a roleplay action. You can ask for: {names}.")
            return False

        return await self.interaction(
            ctx,
            action.name,
            invoker_member,
            target_member,
            interaction_type=const.InteractionType.PASSIVE,
            pairing=pairing,
        )

    # overwriting the .ask() command function docstring here as this is what shows up
    # in the default help text display
    ask.__doc__ = "Ask another member to perform an action on you"

    @ask.autocomplete("action_name")
    async def ask_action_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        names = [name for name in self.action_manager.list() if current.lower() in name]
        return [app_commands.Choice(name=name, value=name) for name in names[:25]]

    async def interaction(
        self,
        ctx: commands.GuildContext,
        action_name: str,
        invoker_member: discord.Member,
        target_member: discord.Member,
        interaction_type: const.InteractionType = const.InteractionType.ACTIVE,
        pairing: str | None = None,
    ):
        """Attempt to perform an action on another member (or yourself)

        Args:
            ctx (commands.GuildContext): The context of the command invocation.
            action_name (str): The name of the roleplay action.
            invoker_member (discord.Member): The member who initiated the command
            target_member (discord.Member): The member being asked to participate.
            interaction_type (Optional, InteractionType): This flag changes the message tense from active
            to passive
            pairing (Optional, str): Only use images with this pairing tag.

        Order of consent:
            Does the action require consent? If not, execute
            If the target has an owner, ask the owner for consent
            If the target is public use? consent


        Returns:
            bool: Return True if conditions were right for roleplay action to happen.
            False otherwise.
        """
        # A slash command has 3 seconds to answer; the consent question or a big gif can take longer
        await ctx.defer()

        action = self.action_manager.get(action_name)
        if not action:
            self.logger.error(f'{self.__class__.__name__}.interaction() called with invalid action "{action_name}"!')
            return False

        # collect settings and owners for invoker and target member
        invoker, invoker_owner = await self.get_party(ctx, invoker_member)
        target, target_owner = await self.get_party(ctx, target_member)

        decision = consent.decide(
            invoker,
            target,
            requester_id=ctx.author.id,
            passive=interaction_type == const.InteractionType.PASSIVE,
            consent_required=action.consent.required,
            action_name=action.name,
        )
        self.logger.debug(
            f"""Interaction:
            action_name : {action_name}
            interaction_type : {interaction_type.value}
            invoker : {invoker}
            target : {target}
            decision : {decision}"""
        )

        if decision.outcome is consent.Outcome.BLOCKED:
            await ctx.send(
                f"**{invoker_member.display_name}**, you can't use that command on **{target_member.display_name}**."
            )
            self.reset_cooldown(ctx, action_name)
            return False

        if decision.outcome is consent.Outcome.REFUSED:
            msg = strings.format_string(const.REFUSAL_MESSAGE, target_member=f"**{target_member.display_name}**")
            await ctx.send(msg)
            self.reset_cooldown(ctx, action_name)
            return False

        if decision.outcome is consent.Outcome.ASK:
            self.logger.debug(f"{action_name} consent is required")
            owners_by_id = {owner.id: owner for owner in (invoker_owner, target_owner) if owner}
            has_consent = await self.ask_for_consent(
                ctx,
                invoker_member,
                target_member,
                action,
                interaction_type=interaction_type,
                owners=[owners_by_id[owner_id] for owner_id in decision.owners],
                ask_target=decision.ask_target,
            )
            if not has_consent:
                self.reset_cooldown(ctx, action_name)
                return False

        # if we've reached this point we should be clear to proceed with the interaction
        await self.send_action_message(
            ctx,
            invoker_member,
            target_member,
            action,
            interaction_type=interaction_type,
            pairing=pairing,
        )

        # Passive (asked-for) actions are performed by the target on the invoker
        doer, receiver = (
            (target_member, invoker_member)
            if interaction_type == const.InteractionType.PASSIVE
            else (invoker_member, target_member)
        )
        if not (doer.bot or receiver.bot):
            await self.tally.record(doer.id, receiver.id, action.name)
        return True

    async def get_party(
        self, ctx: commands.GuildContext, member: discord.Member
    ) -> tuple[consent.Party, discord.Member | None]:
        """A member's roleplay settings, and their owner on this server if they have one."""
        settings = await self.user_settings.config.user(member).all()

        def list_setting(key: str) -> list:
            value = settings.get(key)
            return value if isinstance(value, list) else []

        owner = await self.user_settings.users_manager.get_owner(ctx, member, list_setting("owners"))
        party = consent.Party(
            id=member.id,
            bot=member.bot,
            owner_id=owner.id if owner else None,
            public=bool(settings.get("public")),
            servant=bool(settings.get("servant")),
            selective=bool(settings.get("selective")),
            allowed=frozenset(list_setting("allowed")),
            blocked=frozenset(list_setting("blocked")),
            consented_actions=frozenset(name for name in list_setting("consented_actions") if isinstance(name, str)),
        )
        return party, owner

    async def send_action_message(
        self,
        ctx: commands.GuildContext,
        invoker_member: discord.Member,
        target_member: discord.Member,
        action: Action,
        interaction_type: const.InteractionType = const.InteractionType.ACTIVE,
        pairing: str | None = None,
    ):
        """Sends the final message or Embed for the roleplay command

        Args:
            ctx (commands.GuildContext): The context of the command invocation.
            invoker_member (discord.Member): The user who invoked the command.
            target_member (discord.Member): The member to perform the action on.
            action (Action): Action object containing properties.
            interaction_type (Optional, InteractionType): This flag changes the message tense from active
            to passive
            pairing (Optional, str): Only use images with this pairing tag.
        """
        description = action.description
        self.logger.debug(f"description : {description}")

        if interaction_type == const.InteractionType.ACTIVE:
            description = strings.format_string(
                description,
                invoker_member=invoker_member.mention,
                target_member=target_member.mention,
            )
        # for passive consent type, the invoker is the one receiving the action, so we
        # need to swap the member args
        elif interaction_type == const.InteractionType.PASSIVE:
            description = strings.format_string(
                description,
                invoker_member=target_member.mention,
                target_member=invoker_member.mention,
            )
        else:
            self.logger.error(f"Interaction type {interaction_type} is not supported!")
            return False

        # create the embed object
        embed = discord.Embed(description=description, color=const.EMBED_COLOR)

        # get action credits if it exists and add to default footer text
        footer = const.EMBED_FOOTER
        if action.credits:
            footer = f"{footer}\ncredits: {', '.join(action.credits)}"
        self.logger.debug(f"footer : {footer}")

        image, pairing_missing = await asyncio.to_thread(pick_image, self.images_path / action.name, pairing)
        self.logger.debug(f"image : {image}")
        note = const.PAIRING_MISSING_NOTE.format(pairing=pairing, action=action.name) if pairing_missing else None

        if action.spoiler:
            # embeds can't spoiler their image, so lewd images are sent as a spoilered attachment
            content = f"{description}\n-# {note}" if note else description
            if image is None:
                await ctx.send(content)
            else:
                await ctx.send(content, file=discord.File(image, filename=image.name, spoiler=True))
            return

        if note:
            footer = f"{footer}\n{note}"
        embed.set_footer(text=footer, icon_url=(ctx.me.avatar or ctx.me.default_avatar).url)
        if image is None:
            await ctx.send(embed=embed)
        else:
            embed.set_image(url=f"attachment://{image.name}")
            await ctx.send(embed=embed, file=discord.File(image, filename=image.name))

    async def delete_message(self, ctx: commands.Context, delay: int = const.SHORT_DELETE_TIME):
        """Deletes the command message after a delay, without making the command wait

        Discord ignores it if the message can't be deleted (missing permissions, already
        deleted, or in a DM).

        Args:
            ctx (commands.Context): The context of the command invocation.
            delay (int): Seconds to wait before deleting.
        """
        await ctx.message.delete(delay=delay)

    def reset_cooldown(self, ctx: commands.Context, command_name: str):
        """Reset the cooldown for the invoking user."""
        command = self.bot.get_command(command_name)
        if command is not None:
            command.reset_cooldown(ctx)
            self.logger.debug(f'Reset cooldown on "{command_name}" command.')
        else:
            self.logger.error(f'Invalid command name: "{command_name}".')

    async def ask_for_consent(
        self,
        ctx: commands.GuildContext,
        invoker_member: discord.Member,
        target_member: discord.Member,
        action: Action,
        interaction_type: const.InteractionType = const.InteractionType.ACTIVE,
        owners: list[discord.Member] | None = None,
        ask_target: bool = True,
    ) -> bool:
        """Ask ``owners`` together, then the target member, to consent to the action."""
        invoker_name = f"**{invoker_member.display_name}**"
        target_name = f"**{target_member.display_name}**"

        if owners:
            # interaction type is an Enum, so need it's value as string
            owner_message = getattr(action.consent, f"owner_{interaction_type.value}")
            question = strings.format_string(
                f"{owner_message} {const.CONSENT_QUESTION}",
                owner=" & ".join(owner.mention for owner in owners),
                invoker_member=invoker_name,
                target_member=target_name,
            )
            if not await self.ask_members(
                ctx, question, owners, const.OWNER_REFUSAL_MESSAGE, invoker_member, target_member
            ):
                return False

        if not ask_target:
            return True

        consent_message = getattr(action.consent, interaction_type.value)
        question = strings.format_string(
            f"{consent_message} {const.CONSENT_QUESTION}",
            invoker_member=invoker_name,
            target_member=target_member.mention,
        )
        return await self.ask_members(
            ctx, question, [target_member], const.REFUSAL_MESSAGE, invoker_member, target_member
        )

    async def ask_members(
        self,
        ctx: commands.GuildContext,
        question: str,
        members: list[discord.Member],
        refusal_message: str,
        invoker_member: discord.Member,
        target_member: discord.Member,
    ) -> bool:
        """Ask ``members`` a yes/no question, and say so if they decline or don't answer.

        Args:
            refusal_message (str): Sent when someone declines. ``{owner}`` is replaced
                with who declined.
        """
        self.logger.debug(f'consent_message : "{question}"')
        view = await request_consent(ctx, question, members)

        if view.result is None:
            names = " & ".join(f"**{member.display_name}**" for member in members)
            await ctx.send(const.TIMEOUT_MESSAGE.format(user=names))
            return False

        if not view.result:
            declined_by = next(member for member in members if member.id == view.declined_by)
            await ctx.send(
                strings.format_string(
                    refusal_message,
                    owner=declined_by.display_name,
                    invoker_member=f"**{invoker_member.display_name}**",
                    target_member=f"**{target_member.display_name}**",
                )
            )
            return False

        return True
