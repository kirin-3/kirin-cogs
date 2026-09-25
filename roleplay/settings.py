"""Settings module for the roleplay Discord bot.

This module defines the Settings cog, which dynamically creates commands based on
the user settings configuration. It includes functionality for managing user lists
and toggling boolean flags within the bot's configuration.

Classes:
    - Settings: Cog for managing roleplay settings in a Discord bot.

Functions:
    - create_dynamic_commands: Creates dynamic commands based on the user settings configuration.
    - create_group_command: Creates a group command for managing user lists.
    - create_add_command: Creates an add command for adding users to a list.
    - create_remove_command: Creates a remove command for removing users from a list.
    - create_toggle_command: Creates a toggle command for setting boolean flags.
    - show_settings: Displays roleplay settings for a specified member.
    - settings_embed: Creates an embed showing the current roleplay settings for a member.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import discord
import yaml
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import humanize_list

from . import const, views
from .unicornia.strings import get_indefinite_article
from .user_settings import USER_SETTINGS
from .users import Manager

if TYPE_CHECKING:
    from .main import Roleplay


class Settings:
    """Subclass for managing user settings.

    This class dynamically creates settings commands based on the user settings
    configuration.
    """

    PATH_USER_SETTINGS = Path(__file__).parent / "user_settings.yml"

    def __init__(self, bot: Red, parent: "Roleplay") -> None:
        """Initializes the Settings cog.

        Args:
            bot (Red): The instance of the Red bot.
        """
        self.bot = bot
        self.parent = parent

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.logger.setLevel(const.LOGGER_LEVEL)

        # Existing members' settings are stored under cog name "Settings" +
        # COG_IDENTIFIER with the USER_SETTINGS keys. Changing any of them orphans
        # that data, so the name is pinned instead of taken from this class.
        self.config = Config.get_conf(
            self,
            identifier=const.COG_IDENTIFIER,
            force_registration=True,
            cog_name="Settings",
        )
        default_user = {key: value.get("default", None) for key, value in USER_SETTINGS.items()}
        self.logger.debug(f"default_user:\n{default_user}")
        self.config.register_user(**default_user)

        self.users_manager = Manager(self.bot, self.config)

        # Dynamically create commands based on USER_SETTINGS
        self.create_setting_commands()

    def load_user_settings(self) -> dict:
        with open(self.PATH_USER_SETTINGS, encoding="utf-8") as file:
            try:
                return yaml.safe_load(file)
            except yaml.YAMLError:
                self.logger.error(f"Error trying to parse {self.PATH_USER_SETTINGS}!")
                return {}

    def create_setting_commands(self) -> None:
        """Creates dynamic commands based on the user settings configuration."""
        settings_group = self.parent.settings
        for property, values in USER_SETTINGS.items():
            data_type = type(values.get("default", None))
            self.logger.debug(f"{property} ({data_type}):")
            # TODO: lists are currently used only to store userIDs. We may need to
            # differentiate this if we need to support other types of data
            if data_type is list:
                group_cmd = self.create_group_command(property, values)
                setattr(self.parent, property, group_cmd)
                settings_group.add_command(group_cmd)
                self.logger.debug(f"Group command created for {property}:")

                add_cmd = self.create_add_command(property, values)
                setattr(self.parent, f"add_{property}", add_cmd)
                group_cmd.add_command(add_cmd)
                self.logger.debug(f"Add command created for {property}:")

                remove_cmd = self.create_remove_command(property, values)
                setattr(self.parent, f"remove_{property}", remove_cmd)
                group_cmd.add_command(remove_cmd)
                self.logger.debug(f"Remove command created for {property}:")
            elif data_type is bool:
                # Create toggle command for boolean flags and add it to the parent class
                toggle_cmd = self.create_toggle_command(property, values)
                setattr(self.parent, property, toggle_cmd)
                settings_group.add_command(toggle_cmd)
                self.logger.debug(f"Toggle command created for {property}:")
            else:
                self.logger.error(f'Unknown or unsupported data type ({data_type}) for "{property}"!')

    async def manage_settings(self, ctx: commands.Context, member: discord.Member | None = None):
        """Displays roleplay settings for a specified member.

        This command provides a detailed view of the roleplay settings for a specified
        member, including their public use status, owners, allowed, and blocked users.

        TODO:create interactive UI to manage settings.

        Args:
            ctx (commands.Context): The context of the command invocation.
            member (discord.Member, optional): The member whose settings are to be
            managed. Defaults to the command invoker.

        Returns:
            None
        """
        target = member or ctx.author
        if not await self.can_manage(ctx, target):
            return

        await self.show_settings(ctx, target)

    @staticmethod
    async def can_manage(ctx: commands.Context, member: discord.abc.User) -> bool:
        """Members manage their own settings; only administrators manage someone else's."""
        if member.id == ctx.author.id or (
            isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator
        ):
            return True
        await ctx.send(f"{ctx.author.display_name} is not allowed to use this command on {member.display_name}.")
        return False

    def create_group_command(self, property: str, values: dict) -> commands.Group:
        """Creates a group command for managing user lists.

        Args:
            property (str): The property name.
            values (dict): The values for the property.

        Returns:
            commands.Group: The created group command.
        """

        @commands.group(
            name=property,
            aliases=values.get("aliases"),
            invoke_without_command=True,
        )
        async def group(ctx: commands.Context) -> None:
            if ctx.invoked_subcommand is None:
                user_ids = await self.users_manager.list_users(ctx.author, property)
                users = await self.users_manager.display_names(user_ids)
                label = values.get("label", property.capitalize())
                if not users:
                    await ctx.send(f'No "{label}" for {ctx.author.display_name}.')
                else:
                    await ctx.send(f'"{label}" for {ctx.author.display_name}: {humanize_list(users)}.')

        return group

    def create_add_command(self, property: str, values: dict) -> commands.Command:
        """Creates an add command for adding users to a list.

        Args:
            property (str): The property name.
            values (dict): The values for the property.

        Returns:
            commands.Command: The created add command.
        """

        @commands.command(name=f"add_{property}", aliases=["add"])
        async def add(ctx: commands.Context, user_key: int | str | None = None) -> None:
            await self.parent.delete_message(ctx)
            if user_key:
                await self.users_manager.add_user_to_group(
                    ctx, ctx.author, user_key, property, exclusion_groups=("blocked",)
                )
            else:
                await ctx.send("This command requires a valid user ID, username, or mention.")

        return add

    def create_remove_command(self, property: str, values: dict) -> commands.Command:
        """Creates a remove command for removing users from a list.

        Args:
            property (str): The property name.
            values (dict): The values for the property.

        Returns:
            commands.Command: The created remove command.
        """

        @commands.command(name=f"remove_{property}", aliases=["remove"])
        async def remove(ctx: commands.Context, user_key: int | str | None = None) -> None:
            await self.parent.delete_message(ctx)
            if user_key:
                await self.users_manager.remove_user_from_group(ctx, ctx.author, user_key, property)
            else:
                await ctx.send("This command requires a valid user ID, username, or mention.")

        return remove

    def create_toggle_command(self, property: str, values: dict) -> commands.Command:
        """Creates a toggle command for setting boolean flags.

        Args:
            property (str): The property name.
            values (dict): The values for the property.

        Returns:
            commands.Command: The created toggle command.
        """

        @commands.command(name=property)
        async def toggle(
            ctx: commands.Context,
            member: discord.Member | None = None,
            state: bool | None = None,
        ) -> None:
            await self.parent.delete_message(ctx)

            target = member or ctx.author
            cur_state = await self.config.user(target).get_attr(property)()
            label = values["label"]

            # if a new state wasn't supplied, just show the current state
            if state is None:
                if cur_state:
                    msg = f"{target.display_name} is {get_indefinite_article(label)} {label}."
                else:
                    msg = f"{target.display_name} is not {get_indefinite_article(label)} {label}."
                await ctx.send(msg)
                return

            if not await self.can_manage(ctx, target):
                return

            await self.config.user(target).get_attr(property).set(state)
            await ctx.send(
                f"{target.display_name} is now {get_indefinite_article(label)} {label}."
                if state
                else f"{target.display_name} is no longer {get_indefinite_article(label)} {label}."
            )

        return toggle

    async def show_settings(self, ctx: commands.Context, member: discord.abc.User) -> None:
        """Displays roleplay settings for a specified member.

        Args:
            ctx (commands.Context): The context of the command invocation.
            member (discord.abc.User): The member whose settings are to be displayed.
        """
        self.logger.debug(f"show_settings - member : {member}")

        embed = await self.settings_embed(member)
        view = views.EmbedView(embed, label="Show Settings")
        await ctx.send(
            "Click the button to view your Roleplay settings.",
            view=view,
            delete_after=const.SHORT_DELETE_TIME,
        )

    async def settings_embed(self, member: discord.abc.User) -> discord.Embed:
        """Creates an embed showing the current roleplay settings for a member.

        Args:
            member (discord.abc.User): The member whose settings are to be displayed.

        Returns:
            discord.Embed: The created embed.
        """
        desc_lines = []
        for values in USER_SETTINGS.values():
            emoji = values.get("emoji")
            label = values.get("label")
            description = values.get("description")
            line = f"* {emoji} **{label}** - {description}"
            desc_lines.append(line)
        final_description = "\n".join(desc_lines)

        embed = discord.Embed(
            title=f"Roleplay Settings ({member.display_name}):",
            description=final_description,
            color=const.EMBED_COLOR,
        )
        embed.set_footer(text=const.EMBED_FOOTER)
        embed.set_thumbnail(url=member.display_avatar.url)

        for property, values in USER_SETTINGS.items():
            default = values.get("default")
            data_type = type(default)
            label = values.get("label")

            if data_type is list:
                user_ids = await self.users_manager.list_users(member, property)
                users = await self.users_manager.display_names(user_ids)
                embed.add_field(name=label, value="\n".join(users) or "None", inline=True)
            elif data_type is bool:
                bool_value = await self.config.user(member).get_attr(property)()
                value = const.TRUE_EMOJI if bool_value else const.FALSE_EMOJI
                embed.add_field(name=f"{label} {value}", value="", inline=False)
            else:
                self.logger.error(f'Unsupported data type ({data_type}) for "{property}"!')

        return embed
