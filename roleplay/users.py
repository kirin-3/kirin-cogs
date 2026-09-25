"""Users Module

This module provides a class for managing lists of Discord User IDs in a member's config property.
It includes functionalities for adding, removing, and listing users, checking roles, and handling
permissions for actions involving users.

Classes:
    - Manager: Manages lists of Discord User IDs in a member's config property.
"""

import logging
from dataclasses import dataclass
from random import choice

import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from . import const
from .unicornia.predicates import ExtendedMessagePredicate
from .unicornia.strings import get_indefinite_article
from .user_settings import USER_SETTINGS

# Settings whose value is a list of user IDs
USER_LIST_SETTINGS = [key for key, values in USER_SETTINGS.items() if isinstance(values.get("default"), list)]


@dataclass
class Pronouns:
    subject: str  # e.g., "they"
    object: str  # e.g., "them"
    possessive: str  # e.g., "their"


# defined here instead of const to avoid circular import
PRONOUNS_HE = Pronouns(subject="he", object="him", possessive="his")
PRONOUNS_SHE = Pronouns(subject="she", object="her", possessive="her")
PRONOUNS_THEY = Pronouns(subject="they", object="them", possessive="their")
PRONOUN_ROLES = {
    686112295155138580: PRONOUNS_HE,
    686112244609712139: PRONOUNS_SHE,
    686112332459671600: PRONOUNS_THEY,
}


class Manager:
    """
    This class manages lists of Discord User IDs in a member's config property.

    Attributes:
        bot (Red): The instance of the Redbot bot.
        config (Config): The configuration object for managing settings.
    """

    def __init__(self, bot: Red, config: Config):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.logger.setLevel(const.LOGGER_LEVEL)

        self.bot = bot
        self.config = config

    async def in_group(
        self,
        member: discord.abc.User,
        user_or_id: discord.abc.User | int,
        users_group: str,
    ) -> bool:
        """Checks if a user is in the member's config group.

        Args:
            member (discord.abc.User): Discord member to check.
            user_or_id (discord.abc.User | int): Discord user or user ID to be checked.
            users_group (str): Name of the config property for the users group.
        """
        user_id = user_or_id if isinstance(user_or_id, int) else user_or_id.id
        in_group = user_id in await self.list_users(member, users_group)
        self.logger.debug(f"{user_id} in {member} group {users_group}: {in_group}")
        return in_group

    async def add_user(
        self,
        ctx: commands.Context,
        member: discord.abc.User,
        users_group: str,
        user_id: int,
        permission: dict | None = None,
    ):
        """Adds a user to a member's config.

        Args:
            ctx (commands.Context): The context of the command invocation.
            member (discord.abc.User): Discord member to add user to.
            users_group (str): Name of the config property for the users group.
            user_id (int): Discord user ID to be added.
            permission (Optional[dict]): Dictionary of permission values from member settings.
        """
        target_user = self.bot.get_user(user_id)
        if not target_user:
            await ctx.send(
                f"User with ID {user_id} not found in this guild.",
                delete_after=const.SHORT_DELETE_TIME,
            )
            return

        label = USER_SETTINGS[users_group].get("label", "users list")

        async with self.config.user(member).get_attr(users_group)() as user_ids:
            # members are only allowed to have 1 owner
            if users_group == "owners" and user_ids:
                return await ctx.send(
                    f"{member.display_name} already has {get_indefinite_article(label)} {label}. {choice(const.INSULTS)}",
                    delete_after=const.SHORT_DELETE_TIME,
                )

            # already in the list
            if user_id in user_ids:
                return await ctx.send(
                    f"{target_user.display_name} is already {get_indefinite_article(label)} {label} for {member.display_name}. {choice(const.INSULTS)}",
                    delete_after=const.SHORT_DELETE_TIME,
                )

            # get permission from the prospective member
            if permission and permission.get("required"):
                await ctx.send(
                    permission["permission_ask"].format(target=target_user.mention, author=member.display_name)
                )

                pred = ExtendedMessagePredicate.yes_or_no(ctx, target_user)
                try:
                    await self.bot.wait_for("message", timeout=const.TIMEOUT, check=pred)
                except TimeoutError:
                    return await ctx.send(const.TIMEOUT_MESSAGE.format(user=target_user.display_name))

                if pred.result:
                    user_ids.append(user_id)
                    await ctx.send(
                        permission["permission_accept"].format(
                            target=target_user.display_name, author=member.display_name
                        )
                    )
                else:
                    return await ctx.send(
                        permission["permission_deny"].format(
                            target=target_user.display_name, author=member.display_name
                        )
                    )
            else:
                user_ids.append(user_id)
                return await ctx.send(
                    f"{target_user.display_name} has been added as {get_indefinite_article(label)} {label} for {member.display_name}.",
                    delete_after=const.SHORT_DELETE_TIME,
                )

    async def add_user_to_group(
        self,
        ctx: commands.Context,
        member: discord.abc.User,
        user_key: int | str,
        users_group: str,
        exclusion_groups: tuple[str, ...] = (),
    ):
        """Abstract method to add a user to a member's group list

        Args:
            ctx (commands.Context): The context of the command invocation.
            member (discord.abc.User): The member whose group list is being managed.
            user_key (int | str): The ID, username, or mention of the user to be
            added to the group.
            users_group (str): The name of the group to add the user to.
            exclusion_groups (tuple[str, ...], optional): Groups that the user should not
            be a part of.
        """
        # make sure the user_id is a valid member
        user = await self.get_user(ctx, user_key)
        if user is None:
            return await ctx.send(
                f"Please use a valid user ID, username, or mention. {choice(const.INSULTS)}.",
                delete_after=const.SHORT_DELETE_TIME,
            )

        label = USER_SETTINGS[users_group].get("label", "users list")
        permission = USER_SETTINGS[users_group].get("permission", None)

        # You can't add yourself
        if user.id == member.id:
            return await ctx.send(
                f"{member.display_name} tried to add themselves as {get_indefinite_article(label)} {label}. {choice(const.INSULTS)}",
                delete_after=const.SHORT_DELETE_TIME,
            )

        # check exclusion groups
        for excluded_group in exclusion_groups:
            if await self.in_group(member, user.id, excluded_group):
                excluded_label = USER_SETTINGS[excluded_group].get("label", "users list")
                return await ctx.send(
                    f"{user.display_name} is {get_indefinite_article(excluded_label)} {excluded_label} for {member.display_name}. They can't be added as {get_indefinite_article(label)} {label}. {choice(const.INSULTS)}!",
                    delete_after=const.SHORT_DELETE_TIME,
                )

        # see if the user group needs permissions and pass dict along to function
        await self.add_user(ctx, member, users_group, user.id, permission=permission)

    async def remove_user(
        self,
        ctx: commands.Context,
        member: discord.abc.User,
        user_id: int,
        users_group: str,
    ):
        """Removes a user from a member's config.

        Args:
            ctx (commands.Context): The context of the command invocation.
            member (discord.abc.User): Discord member to remove user from.
            user_id (int): Discord user ID to be removed.
            users_group (str): Name of the config property for the users group.
        """
        user = self.bot.get_user(user_id)
        if not user:
            await ctx.send(f"User with ID {user_id} not found in this guild.")
            return

        label = USER_SETTINGS[users_group].get("label", "users list")
        async with self.config.user(member).get_attr(users_group)() as user_ids:
            if user_id not in user_ids:
                await ctx.send(
                    f"{user.display_name} is not in {get_indefinite_article(label)} {label} for {member.display_name}. {choice(const.INSULTS)}",
                    delete_after=const.SHORT_DELETE_TIME,
                )
            else:
                user_ids.remove(user_id)
                await ctx.send(
                    f"{user.display_name} has been removed as {get_indefinite_article(label)} {label} for {member.display_name}.",
                    delete_after=const.SHORT_DELETE_TIME,
                )

    async def remove_user_from_group(
        self, ctx: commands.Context, member: discord.abc.User, user_key: int | str, users_group: str
    ):
        """Abstract method to remove a user from a member's group list

        Args:
            ctx (commands.Context): The context of the command invocation.
            member (discord.abc.User): The member whose group list is being managed.
            user_key (int | str): The ID, username, or mention of the user to be
            removed from the group.
            users_group (str): The name of the group to remove the user from.
        """
        # make sure the user_id is a valid member
        user = await self.get_user(ctx, user_key)
        if user is None:
            return await ctx.send(
                f"Please use a valid user ID, username, or mention. {choice(const.INSULTS)}",
                delete_after=const.SHORT_DELETE_TIME,
            )

        label = USER_SETTINGS[users_group]["label"]

        # You can't remove yourself
        if user.id == member.id:
            return await ctx.send(
                f"{member.display_name} tried to remove themselves as {get_indefinite_article(label)} {label}. {choice(const.INSULTS)}",
                delete_after=const.SHORT_DELETE_TIME,
            )

        if not await self.in_group(member, user.id, users_group):
            return await ctx.send(
                f"{user.display_name} is not {get_indefinite_article(label)} {label} for {member.display_name}. {choice(const.INSULTS)}",
                delete_after=const.SHORT_DELETE_TIME,
            )

        return await self.remove_user(ctx, member, user.id, users_group)

    async def list_users(self, member: discord.abc.User, users_group: str) -> list[int]:
        """Lists the user IDs in a member's config group.

        Args:
            member (discord.abc.User): Discord member to list users for.
            users_group (str): Name of the config property for the users group.
        """
        user_ids = await self.config.user(member).get_attr(users_group)()
        return list(user_ids) if isinstance(user_ids, list) else []

    async def get_user(self, ctx: commands.Context, user_key: int | str) -> discord.User | None:
        """Gets a user from an ID, mention, username or display name

        Args:
            ctx (commands.Context): The context of the command invocation.
            user_key (int | str): The ID, username, or mention of the user.
        """
        user = None
        if isinstance(user_key, int):
            user = self.bot.get_user(user_key)
        # Check for mention format
        elif user_key.startswith("<@") and user_key.endswith(">"):
            user_id = user_key[2:-1].lstrip("!")
            if user_id.isdigit():
                user = self.bot.get_user(int(user_id))
        else:
            # Search the server's members, or every member the bot can see in a DM,
            # by global username or display name
            members = ctx.guild.members if ctx.guild else self.bot.get_all_members()
            for member in members:
                if user_key in (member.name, member.display_name):
                    user = self.bot.get_user(member.id)
                    break

        if user is None:
            self.logger.warning(f'Unable to find user using "{user_key}".')
        else:
            self.logger.debug(f"Found {user.display_name} ({user.id}) using {user_key} as key.")
        return user

    async def display_names(self, user_ids: list[int]) -> list[str]:
        """Convert a list of user IDs to a list of display names."""
        display_names = []
        for user_id in user_ids:
            try:
                user = await self.bot.fetch_user(user_id)
                display_names.append(user.display_name)
            except discord.NotFound:
                self.logger.error(f"User with ID {user_id} not found.")
                display_names.append(f"Unknown {user_id}")
        return display_names

    async def has_role(self, member: discord.Member, role_key: int | str) -> bool:
        """Checks if the given member has the given role by ID or name.

        Args:
            member (discord.Member): Discord member to check.
            role_key (int | str): ID or name of the role to check for.
        """
        if isinstance(role_key, int):
            role = member.guild.get_role(role_key)
        else:
            role = discord.utils.get(member.guild.roles, name=role_key)

        if role is None:
            self.logger.warning(f"Role '{role_key}' not found. It may not exist on this server.")
            return False

        return role in member.roles

    def get_default_member(self, ctx: commands.GuildContext) -> discord.Member:
        """The member who stands in when an action has no other target: the server's
        configured roleplay bot if it's here, otherwise this bot."""
        member_id = const.DEFAULT_MEMBER_ID.get(ctx.guild.id)
        member = ctx.guild.get_member(member_id) if member_id else None
        return member or ctx.guild.me

    async def get_owner(self, ctx: commands.GuildContext, member: discord.abc.User) -> discord.Member | None:
        """
        TODO: For now, just using the first owner in the users list. I'm not sure what
        we want to do if there multiples. Which owner should we ask for permission?
        All of them? First? Try to figure out who's online or active?
        """
        owners = await self.list_users(member, "owners")
        owner = None
        if owners:
            try:
                owner = await ctx.guild.fetch_member(owners[0])
            except discord.NotFound:
                # the owner left the server
                owner = None
        self.logger.debug(f"Attempted to get owner from {member}: {owner.display_name if owner else None}")
        return owner

    async def get_pronoun(self, member: discord.Member) -> Pronouns:
        for role_id, pronouns in PRONOUN_ROLES.items():
            if await self.has_role(member, role_id):
                return pronouns
        return PRONOUNS_THEY

    async def delete_user_data(self, user_id: int) -> None:
        """Forget a user: their own settings, and their ID in every other member's lists."""
        await self.config.user_from_id(user_id).clear()
        for other_id, data in (await self.config.all_users()).items():
            for key in USER_LIST_SETTINGS:
                user_ids = data.get(key)
                if isinstance(user_ids, list) and user_id in user_ids:
                    await (
                        self.config.user_from_id(other_id)
                        .get_attr(key)
                        .set([kept for kept in user_ids if kept != user_id])
                    )
