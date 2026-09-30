"""Abstract base class for rate responders.

Rate responders are used to generate a rating for a given target member.
The most basic form of these is a very simple call/response that will
create an embed with a title, description, thumbnail and a rating bar.

Embed properties (class attributes):
    title: str = "[RATE]"
    description: str = "{target} is {rating}%"
    thumbnail: str = None (the target's avatar)
    footer: str = None
    color: int = the bot's embed colour
    bar_full: tuple[str, ...] = ("🟪",)  (cycled, so several emojis make a pattern)
    bar_empty: str = "⬛"

The rating is a daily roll between 0 and 100, the same for a member and
topic until midnight UTC. Override `respond` and call `send_rating` with
another number to compute it some other way, or with None to hide the bar.

User-specific overrides can be defined in the `user_overrides` dictionary.
This dictionary should be defined as a [user.id] = {[embed properties:values]}.
If a value is a list, a random choice will be made. This is handy for things like
multiple descriptions or images. A "rating" key replaces the rating itself
(None hides the bar), for jokes like "is the gay".

Rating-specific overrides can be defined in the `rating_overrides` dictionary.
This dictionary should be defined as a [rating] = {[embed properties:values]}.
Keys are sorted in descending order, and the first key that is less than or equal
to the rating will be used.
Like the user-specific overrides, if a value is a list, a random choice
will be made.
Note: user-specific overrides take precedence over rating-specific overrides.
"""

import random
import re
from datetime import UTC, date, datetime
from typing import Any

import discord

from .. import const
from ..unicornia import strings
from .base_text_responder import BaseTextResponder

EMBED_PROPERTIES = ("title", "description", "thumbnail", "footer", "color", "bar_full", "bar_empty")


def daily_roll(member_id: int, topic: str, day: date | None = None) -> int:
    """0 to 100, the same for a member and topic all day (UTC). String seeds hash the same in every process."""
    return random.Random(f"{topic}:{member_id}:{day or datetime.now(UTC).date()}").randint(0, 100)


def rating_bar(rating: float, full: tuple[str, ...], empty: str, size: int = 10) -> str:
    """A bar of `size` emojis, clamped so ratings over 100% are a full bar."""
    filled = max(0, min(size, round(rating / 100 * size)))
    return "".join(full[i % len(full)] for i in range(filled)) + empty * (size - filled)


class BaseRateResponder(BaseTextResponder):
    enabled: bool = False

    title: str = "[RATE]"
    description: str = "{target} is {rating}%"
    thumbnail: str | None = None
    footer: str | None = None
    color: int = const.UNICORNIA_BOT_COLOR
    bar_full: tuple[str, ...] = ("🟪",)
    bar_empty: str = "⬛"

    # this enables hard-coding overrides for specific user ids
    # dictionary should be defined as a [user.id] = {[embed properties:values]}
    # if a value is a list, a random choice will be made. This is handy for things like
    # multiple descriptions or images.
    user_overrides: dict = {}

    # this enables changing embed properties for rating values
    rating_overrides: dict = {}

    # set by RateResponder before each respond()
    topic: str = ""

    def get_property(self, property: str, member: discord.Member, rating: float):
        """Retrieve a property value for a given target member and rating.

        1. This method first checks if the target member has any user-specific overrides.
        If an override exists for the given property, it returns that value.
        2. If no user-specific override is found, it checks for rating-specific overrides
        in descending order of rating. If a rating-specific override is found, it returns
        that value.
        3. If no overrides are found, it returns the default property value.
        """

        if member.id in self.user_overrides:
            value = self.user_overrides[member.id].get(property, getattr(self, property))
            return random.choice(value) if isinstance(value, list) else value

        for key in sorted(self.rating_overrides.keys(), reverse=True):
            if rating >= key:
                value = self.rating_overrides[key].get(property, getattr(self, property))
                return random.choice(value) if isinstance(value, list) else value

        return getattr(self, property)

    def display_rating(self, rating: float) -> float | None:
        """The number shown and drawn as a bar; None hides the bar."""
        return rating

    async def send_rating(
        self,
        message: discord.Message,
        target: discord.Member,
        rating: float | None,
        *,
        footer: str | None = None,
        **overrides: Any,
    ) -> None:
        """Reply with the rating embed. `overrides` replace embed properties outright."""
        rating = self.user_overrides.get(target.id, {}).get("rating", rating)
        props = {name: self.get_property(name, target, rating or 0) for name in EMBED_PROPERTIES} | overrides
        shown = None if rating is None else self.display_rating(rating)

        description = strings.format_string(props["description"], target=target.display_name, rating=shown)
        if shown is not None:
            description += f"\n\n{rating_bar(shown, props['bar_full'], props['bar_empty'])}  **{shown}%**"

        await self.send_embed(
            message,
            title=props["title"],
            description=description,
            thumbnail=props["thumbnail"] or target.display_avatar.url,
            footer=footer or props["footer"],
            color=props["color"],
            as_reply=True,
        )

    async def respond(
        self,
        message: discord.Message,
        target: discord.Member,
        match: re.Match,
    ):
        await self.send_rating(message, target, daily_roll(target.id, self.topic.lower()))
