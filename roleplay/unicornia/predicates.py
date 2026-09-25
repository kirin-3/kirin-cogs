from collections.abc import Iterable

import discord
from redbot.core import commands


class ExtendedMessagePredicate:
    """A ``wait_for("message")`` check that accepts many forms of yes or no.

    Only messages from ``users`` in the invoking channel count. ``result`` becomes
    ``False`` on the first no, and ``True`` once every user has said yes.
    """

    POSITIVES = [
        "yes",
        "y",
        "yup",
        "yeah",
        "affirmative",
        "absolutely",
        "sure",
        "ok",
        "okay",
        "aye",
        "ja",  # German/Dutch
        "da",  # Russian
        "si",  # Spanish/Italian
        "oui",  # French
        "sim",  # Portuguese
        "hai",  # Japanese
        "tak",  # Polish
        "ano",  # Czech
        "igen",  # Hungarian
        "evet",  # Turkish
    ]
    NEGATIVES = [
        "no",
        "n",
        "nope",
        "nah",
        "negative",
        "never",
        "not",
        "nay",
        "nein",  # German
        "nien",  # Polish
        "niet",  # Russian
        "non",  # French/Italian
        "nada",  # Spanish
        "não",  # Portuguese
        "いいえ",  # Japanese
        "hayır",  # Turkish  # noqa: RUF001
        "nie",  # Dutch
        "nem",  # Hungarian
        "ne",  # Czech
        "yok",  # Turkish
    ]

    def __init__(self, channel_id: int, user_ids: set[int]) -> None:
        self.channel_id = channel_id
        self.user_ids = user_ids
        self.positive_responses: set[int] = set()
        self.result: bool | None = None

    @classmethod
    def yes_or_no(
        cls, ctx: commands.Context, users: discord.abc.User | Iterable[discord.abc.User]
    ) -> "ExtendedMessagePredicate":
        """Match a yes or no from ``users`` in ``ctx.channel``."""
        user_ids = {users.id} if isinstance(users, discord.abc.User) else {u.id for u in users}
        return cls(ctx.channel.id, user_ids)

    def __call__(self, message: discord.Message) -> bool:
        if message.channel.id != self.channel_id or message.author.id not in self.user_ids:
            return False
        content = message.content.lower()
        if content in self.NEGATIVES:
            self.result = False
            return True
        if content in self.POSITIVES:
            self.positive_responses.add(message.author.id)
            if self.positive_responses == self.user_ids:
                self.result = True
                return True
        return False
