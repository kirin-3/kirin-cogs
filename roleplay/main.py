"""Main module for roleplay bot"""

import logging
from pathlib import Path
from random import choice
from urllib.parse import urlparse

import aiohttp
import discord
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import humanize_list, inline

from . import __version__, consent, const
from .actions import Action, ActionManager
from .embed import Embed
from .help import Help
from .settings import Settings
from .unicornia import strings, web
from .views import request_consent


class Roleplay(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.logger.setLevel(const.LOGGER_LEVEL)

        self.action_manager = ActionManager()
        self.helper = Help(self.action_manager)
        self.user_settings = Settings(bot, self)

        # action commands are added to the bot directly, see create_action_command()
        self.action_commands: list[commands.Command] = []

        # for downloading action images, see http_session()
        self.session: aiohttp.ClientSession | None = None

        self.create_action_commands()

        self.logger.info("-" * 32)
        self.logger.info(f"{self.__class__.__name__} v({__version__}) initialized!")
        self.logger.info("-" * 32)

        # Asynchronously update the action_manager
        # this lets us look for locally cached images once Red has set up the cog's
        # data folder
        bot.loop.create_task(self.initialize())

    @property
    def images_path(self) -> Path:
        """Locally cached action images, one folder per action."""
        return cog_data_path(self) / "images"

    async def initialize(self):
        await self.bot.wait_until_red_ready()
        self.action_manager.update(self.images_path)

    def http_session(self) -> aiohttp.ClientSession:
        """The cog's HTTP session, created on first use (it has to be created while the
        bot's event loop is running) and closed when the cog is unloaded."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def cog_unload(self):
        # the bot only removes the cog's own commands when it's unloaded, so the action
        # commands added to it directly have to be removed here or reloading will fail
        for command in self.action_commands:
            if self.bot.all_commands.get(command.name) is command:
                self.bot.remove_command(command.name)

        if self.session is not None:
            await self.session.close()

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Remove the user's roleplay settings and their ID from every other member's lists."""
        await self.user_settings.users_manager.delete_user_data(user_id)

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

    @admin.command()
    async def download(self, ctx: commands.Context):
        """Downloads all action images into the cog's data folder"""
        images_path = self.images_path
        downloaded = skipped = failed = 0

        async with ctx.typing():
            for action in self.action_manager.actions:
                for image_url in action.image_urls:
                    saved = await web.save_image_from_url(
                        self.http_session(), image_url, images_path, action.name, action.spoiler
                    )
                    if saved is None:
                        failed += 1
                    elif saved:
                        downloaded += 1
                    else:
                        skipped += 1

        # start using the images just downloaded
        self.action_manager.update(images_path)

        await ctx.send(
            f"Roleplay action images saved to: {images_path}\n"
            f"Downloaded: {downloaded}, already saved: {skipped}, failed: {failed}"
        )

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
        async def command_method(ctx: commands.GuildContext, *, target_member: discord.Member | None = None):
            """Executes the specified action for the given member.

            Args:
                ctx (commands.GuildContext): The context of the command invocation.
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
            )

            # if the interaction wasn't successful, reset the cooldown for this command
            if result is not True:
                self.reset_cooldown(ctx, action_name)

            return result

        command_method.__name__ = action_name
        command_method.__doc__ = help_text

        # include capitalized version of command and aliases
        all_aliases = [*aliases, *(a.capitalize() for a in aliases), action_name.capitalize()]

        command = commands.command(name=action_name, aliases=all_aliases)(command_method)
        command = commands.cooldown(const.COOLDOWN_RATE, const.COOLDOWN_TIME, commands.BucketType.channel)(command)
        command = commands.bot_has_permissions(embed_links=True)(command)
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

    @commands.command(aliases=["askfor", "get", "giveme", "gimme", "request"])
    @commands.guild_only()
    async def ask(
        self,
        ctx: commands.GuildContext,
        action_name: str,
        target_member: discord.Member | None = None,
    ):
        """Ask another member to perform an action on you

        This command serves as a wrapper for .interaction(). It allows a member to ask
        another member to perform an action on themselves.

        Args:
            ctx (commands.GuildContext): The context of the command invocation.
            action_name (str): The name of the roleplay action.
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
        )

    # overwriting the .ask() command function docstring here as this is what shows up
    # in the default help text display
    ask.__doc__ = "Ask another member to perform an action on you"

    async def interaction(
        self,
        ctx: commands.GuildContext,
        action_name: str,
        invoker_member: discord.Member,
        target_member: discord.Member,
        interaction_type: const.InteractionType = const.InteractionType.ACTIVE,
    ):
        """Attempt to perform an action on another member (or yourself)

        Args:
            ctx (commands.GuildContext): The context of the command invocation.
            action_name (str): The name of the roleplay action.
            invoker_member (discord.Member): The member who initiated the command
            target_member (discord.Member): The member being asked to participate.
            interaction_type (Optional, InteractionType): This flag changes the message tense from active
            to passive

        Order of consent:
            Does the action require consent? If not, execute
            If the target has an owner, ask the owner for consent
            If the target is public use? consent


        Returns:
            bool: Return True if conditions were right for roleplay action to happen.
            False otherwise.
        """
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
        )
        return True

    async def get_party(
        self, ctx: commands.GuildContext, member: discord.Member
    ) -> tuple[consent.Party, discord.Member | None]:
        """A member's roleplay settings, and their owner on this server if they have one."""
        settings = await self.user_settings.config.user(member).all()

        def user_ids(key: str) -> list[int]:
            value = settings.get(key)
            return value if isinstance(value, list) else []

        owner = await self.user_settings.users_manager.get_owner(ctx, member, user_ids("owners"))
        party = consent.Party(
            id=member.id,
            bot=member.bot,
            owner_id=owner.id if owner else None,
            public=bool(settings.get("public")),
            servant=bool(settings.get("servant")),
            selective=bool(settings.get("selective")),
            allowed=frozenset(user_ids("allowed")),
            blocked=frozenset(user_ids("blocked")),
        )
        return party, owner

    async def send_action_message(
        self,
        ctx: commands.GuildContext,
        invoker_member: discord.Member,
        target_member: discord.Member,
        action: Action,
        interaction_type: const.InteractionType = const.InteractionType.ACTIVE,
    ):
        """Sends the final message or Embed for the roleplay command

        Args:
            ctx (commands.GuildContext): The context of the command invocation.
            invoker_member (discord.Member): The user who invoked the command.
            target_member (discord.Member): The member to perform the action on.
            action (Action): Action object containing properties.
            interaction_type (Optional, InteractionType): This flag changes the message tense from active
            to passive
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

        # get a random image from the list of images: a URL, or a locally cached file
        image = choice(action.images)
        is_url = urlparse(image).scheme in ("http", "https")
        self.logger.debug(f"image {'URL' if is_url else 'filepath'} : {image}")

        # EMBEDS WON'T SPOILER IMAGES INSIDE THEM
        # Embed.spoiler_image() creates manages a local cache and uses file attachments
        # which makes for a bit nicer presentation
        embed.set_footer(text=footer, icon_url=(ctx.me.avatar or ctx.me.default_avatar).url)
        if is_url and action.spoiler:
            try:
                async with ctx.typing():
                    file = await Embed.spoiler_image(self.http_session(), image)
            except (aiohttp.ClientError, TimeoutError):
                # still show the action, just without its image
                self.logger.exception(f"Unable to download {image}!")
                await ctx.send(description)
            else:
                await ctx.send(description, file=file)
        elif is_url:
            embed.set_image(url=image)
            await ctx.send(embed=embed)
        else:
            file_path = Path(image)
            file = discord.File(fp=file_path, filename=file_path.name)
            if action.spoiler:
                await ctx.send(description, file=file)
            else:
                embed.set_image(url=f"attachment://{file_path.name}")
                await ctx.send(embed=embed, file=file)

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
