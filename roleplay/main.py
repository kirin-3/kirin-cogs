"""Main module for roleplay bot"""

import asyncio
import logging
from pathlib import Path
from random import choice
from urllib.parse import urlparse

import discord
import requests
from redbot.core import commands
from redbot.core.bot import Red
from redbot.core.data_manager import cog_data_path
from redbot.core.utils.chat_formatting import humanize_list, inline

from . import __version__, const
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

    async def cog_unload(self):
        # the bot only removes the cog's own commands when it's unloaded, so the action
        # commands added to it directly have to be removed here or reloading will fail
        for command in self.action_commands:
            if self.bot.all_commands.get(command.name) is command:
                self.bot.remove_command(command.name)

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
                    saved = await asyncio.to_thread(
                        web.save_image_from_url, image_url, images_path, action.name, action.spoiler
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

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Sets up listener to override default help menu for cog

        Args:
            ctx (commands.Context): The context of the command invocation.
            error (commands.CommandError): CommandError passed in as arg
        """
        self.logger.error(f"Command Error: {error}")
        if isinstance(error, commands.CommandNotFound) and ctx.command is None:
            # don't send the roleplay help otherwise it will spam for
            # every & command
            # await self.roleplay_help.roleplay(ctx)
            pass

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

        # collection settings for invoker and target member
        target_public = await self.user_settings.config.user(target_member).public()
        target_servant = await self.user_settings.config.user(target_member).servant()
        target_selective = await self.user_settings.config.user(target_member).selective()
        is_blocked = await self.check_blocked(ctx, invoker_member, target_member)
        is_allowed = await self.user_settings.users_manager.in_group(target_member, invoker_member, "allowed")
        invoker_owner = await self.user_settings.users_manager.get_owner(ctx, invoker_member)
        target_owner = await self.user_settings.users_manager.get_owner(ctx, target_member)

        self.logger.debug(
            f"""Ineraction:
            action_name : {action_name}
            invoker_member : {invoker_member}
            target_member : {target_member}
            interaction_type : {interaction_type.value}
            target_public : {target_public}
            target_servant : {target_servant}
            target_selective : {target_selective}
            is_blocked : {is_blocked}
            is_allowed : {is_allowed}
            invoker_owner : {invoker_owner}
            target_owner : {target_owner}"""
        )

        # make sure neither member is blocked by the other
        if is_blocked:
            self.reset_cooldown(ctx, action_name)
            return False

        # If the invoker_member owns the target member
        if invoker_member == target_owner:
            await self.send_action_message(
                ctx,
                invoker_member,
                target_member,
                action,
                interaction_type=interaction_type,
            )
            return True

        # If the invoker_member calling the command is in the target's allowed list, execute the command
        if is_allowed:
            await self.send_action_message(
                ctx,
                invoker_member,
                target_member,
                action,
                interaction_type=interaction_type,
            )
            return True

        # The target is never asked when they asked for this themselves (the command was
        # used without another member), or when they're a bot, since bots can't answer
        target_can_consent = target_member != ctx.author and not target_member.bot

        # if the target has the 'selective user' flag, then decline the command unless:
        # the invoker is their owner or in their allowed list (both handled above)
        # the interaction is active and they are public use
        # the interaction is passive and they are servant
        if (
            target_can_consent
            and target_selective
            and not (interaction_type == const.InteractionType.ACTIVE and target_public)
            and not (interaction_type == const.InteractionType.PASSIVE and target_servant)
        ):
            msg = strings.format_string(const.REFUSAL_MESSAGE, target_member=f"**{target_member.display_name}**")
            await ctx.send(msg)
            self.reset_cooldown(ctx, action_name)
            return False

        # The target has to consent if they can and:
        # - The action is passive and the target is not a servant.
        # - The action is active, requires consent, and the target is not public use.
        target_consent_needed = target_can_consent and (
            (interaction_type == const.InteractionType.PASSIVE and not target_servant)
            or (interaction_type == const.InteractionType.ACTIVE and action.consent.required and not target_public)
        )
        # Consent is also required if the invoker or target has an owner.
        requires_consent = bool(invoker_owner or target_owner or target_consent_needed)

        if requires_consent:
            self.logger.debug(f"{action_name} consent is required")
            has_consent = await self.ask_for_consent(
                ctx,
                invoker_member,
                target_member,
                action,
                interaction_type=interaction_type,
                invoker_owner=invoker_owner,
                target_owner=target_owner,
                ask_target=target_consent_needed,
            )
            if has_consent is not True:
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
                    _, file = await asyncio.to_thread(Embed.spoiler_image, image, embed)
            except requests.RequestException:
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

    async def check_blocked(
        self,
        ctx: commands.GuildContext,
        invoker_member: discord.Member,
        target_member: discord.Member,
    ):
        # If the member calling the command is in the target member's blocked list, or
        # vice-versa send message that the command can't be used
        target_member_blocked = await self.user_settings.users_manager.in_group(
            invoker_member, target_member, "blocked"
        )
        invoker_member_blocked = await self.user_settings.users_manager.in_group(
            target_member, invoker_member, "blocked"
        )
        is_blocked = invoker_member_blocked or target_member_blocked
        self.logger.debug(
            f"""Checking blocked status:
                invoker_member_blocked : {invoker_member_blocked}
                target_member_blocked : {target_member_blocked}
                is blocked : {is_blocked}"""
        )
        if is_blocked:
            await ctx.send(
                f"**{invoker_member.display_name}**, you can't use that command on **{target_member.display_name}**."
            )
            return True
        return False

    async def ask_for_consent(
        self,
        ctx: commands.GuildContext,
        invoker_member: discord.Member,
        target_member: discord.Member,
        action: Action,
        interaction_type: const.InteractionType = const.InteractionType.ACTIVE,
        invoker_owner: discord.Member | None = None,
        target_owner: discord.Member | None = None,
        ask_target: bool = True,
    ) -> bool:
        """Ask the owners involved, then the target member, to consent to the action.

        Owners are asked first. The target's owner answers for the target, so the target
        is only asked when they have no owner, and ``ask_target`` is True.
        """
        self.logger.debug(
            f"""get_consent():
            ctx: {ctx}
            \tinvoker_member: {invoker_member}
            \ttarget_member: {target_member}
            \taction: {action.name}
            \tinteraction_type={interaction_type}
            \tinvoker_owner: {invoker_owner}
            \ttarget_owner: {target_owner}
            \task_target: {ask_target}
            """
        )

        # collect owners for invoker and target members
        if not invoker_owner:
            invoker_owner = await self.user_settings.users_manager.get_owner(ctx, invoker_member)
        if not target_owner:
            target_owner = await self.user_settings.users_manager.get_owner(ctx, target_member)

        # if both invoker and target have owners, ask both for permission together.
        # The invoker's owner isn't asked when they're the target, who answers below
        owners: list[discord.Member] = []
        if invoker_owner and invoker_owner != target_member:
            owners.append(invoker_owner)
        if target_owner and target_owner not in owners:
            owners.append(target_owner)

        if owners:
            # interaction type is an Enum, so need it's value as string
            owner_message = getattr(action.consent, f"owner_{interaction_type.value}")
            consent_message = strings.format_string(
                f"{owner_message} {const.CONSENT_QUESTION}",
                owner=" & ".join(owner.mention for owner in owners),
                invoker_member=f"**{invoker_member.display_name}**",
                target_member=f"**{target_member.display_name}**",
            )
            self.logger.debug(f'consent_message : "{consent_message}"')
            view = await request_consent(ctx, consent_message, owners)

            if view.result is None:
                owners_display_name = " & ".join(f"**{owner.display_name}**" for owner in owners)
                await ctx.send(const.TIMEOUT_MESSAGE.format(user=owners_display_name))
                return False

            # name the owner who declined
            if not view.result:
                refusing_owner = next(owner for owner in owners if owner.id == view.declined_by)
                refusal_message = const.OWNER_REFUSAL_MESSAGE.format(
                    owner=refusing_owner.display_name,
                    invoker_member=f"**{invoker_member.display_name}**",
                    target_member=f"**{target_member.display_name}**",
                )
                await ctx.send(refusal_message)
                return False

            # the target's owner has given consent for them
            if target_owner:
                return True

        if not ask_target:
            return True

        # Otherwise, ask the target member for consent
        # interaction type is an Enum, so need it's value as string
        consent_message = getattr(action.consent, interaction_type.value)
        consent_message = f"{consent_message} {const.CONSENT_QUESTION}"
        consent_message = strings.format_string(
            consent_message,
            invoker_member=f"**{invoker_member.display_name}**",
            target_member=target_member.mention,
        )
        self.logger.debug(f'consent_message : "{consent_message}"')
        view = await request_consent(ctx, consent_message, [target_member])

        if view.result is None:
            await ctx.send(const.TIMEOUT_MESSAGE.format(user=f"**{target_member.display_name}**"))
            return False

        if not view.result:
            refusal_message = const.REFUSAL_MESSAGE.format(target_member=f"**{target_member.display_name}**")
            await ctx.send(refusal_message)
            return False

        return True
