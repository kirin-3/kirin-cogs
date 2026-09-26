import glob
import importlib
import logging
import re
from pathlib import Path

import discord
from redbot.core import commands
from redbot.core.bot import Red

from . import __version__, const
from .responders.base_text_responder import BaseTextResponder


class ResponderCog(commands.Cog):
    RESPONDERS_PATH = Path(__file__).parent / "responders"
    RESPONDER_FILE_PATHS = [Path(p) for p in glob.glob(str(RESPONDERS_PATH / "*.py"))]

    # Pattern used to separate potential trigger from the target member
    # ^(.*?): Captures any characters (non-greedy) at the beginning of the string as trigger.
    # \s+: Matches one or more whitespace characters.
    # (<@!?\d{17,19}>|\d{17,19}): Matches and captures a mention or user ID.
    COMMAND_USER_PATTERN = re.compile(r"^(.*?)\s+(<@!?\d{17,19}>|\d{17,19})$")

    def __init__(self, bot: Red):
        self.logger = logging.getLogger("red.kirin_cogs.responder")
        self.logger.setLevel(const.LOG_LEVEL)

        self.bot = bot

        self.responders = self._init_responders()

        self.logger.info("-" * 32)
        self.logger.info(f"{self.__class__.__name__} v({__version__}) initialized!")
        self.logger.info("-" * 32)

    def _init_responders(self):
        """Collect all responder classes from the responders directory and instantiates them."""
        responders = []

        for filepath in self.RESPONDER_FILE_PATHS:
            module_name = filepath.stem

            if module_name == "__init__":
                continue

            module = importlib.import_module(f".responders.{module_name}", package=__package__)
            self.logger.debug(f"Loaded module: {module}")

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseTextResponder) and getattr(attr, "enabled", False):
                    self.logger.debug(f'Adding "{attr_name}" to responders')
                    class_obj = attr(parent=self, bot=self.bot)
                    responders.append(class_obj)

        return responders

    def _get_responder(self, trigger: str) -> tuple[BaseTextResponder, re.Match] | None:
        """Retrieve the appropriate responder based on the given trigger.

        This method iterates through the list of responders and checks if any of them
        have patterns that match the provided trigger string. If a match is found, the
        corresponding responder is returned. If no match is found, None is returned.

        Args:
            trigger (str): The trigger string to match against the responder patterns.

        Returns:
            Union[BaseTextResponder, None]: The responder that matches the trigger, or None if no match is found.
        """
        for responder in self.responders:
            self.logger.debug(f"Checking responder: {responder} using patterns: {responder.patterns}")

            # Make sure the responder has a valid list patterns to match against
            if not hasattr(responder, "patterns") or not responder.patterns:
                self.logger.error(f"Responder {responder} has no patterns!")
                continue

            for pattern in responder.patterns:
                match = re.search(pattern, trigger, responder.regex_flags)
                if match:
                    return responder, match
                else:
                    self.logger.debug(f"No match for {trigger} in pattern: {pattern}")

        return None

    async def _get_target_member(
        self, message: discord.Message, author: discord.Member, target_key: str | None
    ) -> discord.Member | None:
        """Retrieves the target member from a message.

        If the target_key is None, the author of the message is returned.
        Otherwise, it attempts to find and return the member specified by the target_key.

        Args:
            message (discord.Message): The message object containing the author and context.
            target_key (Union[str, None]): The key used to identify the target member. If None, the message author is returned.

        Returns:
            discord.Member: The member object corresponding to the target_key or the message author if target_key is None.
        """
        if target_key is None:
            return author

        # COMMAND_USER_PATTERN only captures a mention or a raw user ID
        assert message.guild is not None
        member_id = int(target_key.strip("<@!>"))
        if member := message.guild.get_member(member_id):
            return member
        try:
            return await message.guild.fetch_member(member_id)
        except discord.NotFound:
            return None

    def is_allowed_channel(self, guild_id: int, channel_id: int) -> bool:
        # Check if the message is in a guild's allowed channel
        return channel_id in const.SERVER_PERMISSIONS.get(guild_id, {}).get("allowed_channels", {})

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Event listener that is called when a message is created and sent to a channel.

        Args:
            message (discord.Message): The message that was sent.

        Returns:
            None

        Behavior:
            - Ignores messages sent by bots.
            - Ignores messages sent in channels not listed in ALLOWED_CHANNEL_IDS.
            - Extracts the trigger and target key from the message content using COMMAND_USER_PATTERN.
            - Finds a responder for the trigger.
            - Checks if the responder is on cooldown and replies with a cooldown message if necessary.
            - Attempts to find the target member using the target key.
            - Updates the responder's last called time and calls the responder's respond method.
        """

        # Ignore messages from all bots (and webhooks, which aren't members)
        author = message.author
        if author.bot or not isinstance(author, discord.Member):
            return

        # Check if the message is in a guild's allowed channel
        # (DMs have no guild, so we skip them)
        if message.guild is None or not self.is_allowed_channel(message.guild.id, message.channel.id):
            return
        if await self.bot.cog_disabled_in_guild(self, message.guild):
            return
        if not await self.bot.allowed_by_whitelist_blacklist(author):
            return

        # Separate trigger from potential target member
        match = self.COMMAND_USER_PATTERN.match(message.content.strip())
        if match:
            trigger = match.group(1).strip()
            target_key = match.group(2).strip()
        else:
            trigger = message.content
            target_key = None

        # Try and find a responder for any triggers in the message
        found = self._get_responder(trigger)
        if found is None:
            return
        responder, responder_match = found

        # Check if the responder is on cooldown
        if responder.is_on_cooldown() and not author.guild_permissions.administrator:
            if not responder.silent_cooldown:
                await message.reply(
                    f"Please wait {responder.get_cooldown_remaining()}s before using this command again."
                )
            return

        # Get the target discord.Member object
        target_member = await self._get_target_member(message, author, target_key)
        if target_member is None:
            await message.reply(f'Unable to find a member using "{target_key}".')
            return None

        # Update the last called time for the responder and call the respond method
        responder.update_last_called()

        self.logger.debug(
            f"Calling responder: {responder}\nmessage: {message.content}\ntarget_member: {target_member}\nmatch: {responder_match}"
        )
        return await responder.respond(message, target_member, responder_match)
