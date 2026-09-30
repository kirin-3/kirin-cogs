"""Dom/Sub rating responder.

This responder calculates a rating based on the roles a member has.
The roles are assigned a value based on their dominance or submissiveness.
The total rating is the sum of the dominant roles minus the sum of the
submissive roles.
The rating is then converted to a percentage and displayed to the user.

Note, these values are not normalized as displaying very high ratings
values is 500% more fun.
"""

import re

import discord

from .. import const
from .base_rate_responder import BaseRateResponder


class DomRate(BaseRateResponder):
    # default title, description, and thumnail is for unknown or 0% rating
    title = "❯ Mysterious..."
    description = "{target} is 1000% mysterious..."
    thumbnail = r"https://cdn.discordapp.com/emojis/828672418318778398.gif"
    footer = "Results scientifically calculated based on member roles."
    color = 0x607D8B

    dominant_properties = {
        "title": "❯ Dominant",
        "description": "{target} is {rating}% Dominant.",
        "thumbnail": r"https://cdn.discordapp.com/emojis/695147901407592499.webp?size=128&quality=lossless",
        "color": 0xB00020,
        "bar_full": ("🟥",),
    }
    submissive_properties = {
        "title": "❯ Submissive",
        "description": "{target} is {rating}% Submissive.",
        "thumbnail": r"https://cdn.discordapp.com/emojis/729249758715183144.webp?size=128&quality=lossless",
        "color": 0xFF8FC8,
        "bar_full": ("🩷",),
    }

    user_overrides = {
        const.KIRIN_ID: {**submissive_properties, "rating": 690},
        const.RUFFIANA_ID: {
            **submissive_properties,
            "title": "❯ Submissive Fuck Toy",
            "description": "{target} is {rating}% fuck toy.",
            "thumbnail": r"https://cdn.discordapp.com/emojis/816087120526442506.webp?size=128&quality=lossless&animated=true",
            "rating": 100,
        },
        # junny
        89582933735665664: {**dominant_properties, "rating": 666},
        # Maid ice:3
        819276102325239840: {**submissive_properties, "rating": 869},
        # berry
        1058458210060751039: {**submissive_properties, "rating": 666},
    }

    SUB_ROLES = {
        1329908302187855972: 1.00,
        686097362107498504: 1.00,
        768103786119823380: 0.75,
        768103783498121296: 0.75,
        694788843207131246: 1.00,
        694788849020305451: 0.75,
        694788851155337236: 0.20,
        694788853419999352: 0.20,
        694788854942531607: 0.50,
        1074675006006644736: 0.05,
        696082750775492688: 0.20,
        694790765460848701: 1.00,
        696048918248554627: 1.00,
        708022873058574396: 0.25,
        686098506834116620: 0.05,
        686098381214711837: 1.00,
    }

    DOM_ROLES = {
        1329908395578495068: 1.00,
        686097057190379537: 1.00,
        686097106083119115: 1.00,
        694788857371033640: 1.00,
        694788859015462923: 0.25,
        694788860760031243: 0.25,
        694789801353805862: 0.25,
        694789803153162290: 0.25,
        694790101095546890: 0.25,
        694790104044142612: 1.00,
        694790108230189087: 0.25,
        686098541831127048: 0.10,
        811471307106942996: 0.50,
    }

    def get_role_rating(self, member: discord.Member) -> float:
        role_ids = {r.id for r in member.roles}
        dom_rating = sum(value for role, value in self.DOM_ROLES.items() if role in role_ids)
        sub_rating = sum(value for role, value in self.SUB_ROLES.items() if role in role_ids)
        return dom_rating - sub_rating

    def get_property(self, property: str, member: discord.Member, rating: float):
        """Extends base class to include dominant/submissive properties."""

        if member.id in self.user_overrides:
            return self.user_overrides[member.id].get(property, getattr(self, property))

        # get the property from dominant or submissive if rating if it exists
        if rating > 0.0:
            return self.dominant_properties.get(property, getattr(self, property))
        elif rating < 0.0:
            return self.submissive_properties.get(property, getattr(self, property))

        return getattr(self, property)

    def display_rating(self, rating: float) -> float | None:
        """Submissive ratings are negative; show them positive, and no bar for the mysterious 0."""
        return abs(rating) or None

    async def respond(
        self,
        message: discord.Message,
        target: discord.Member,
        match: re.Match,
    ):
        """Rate from the member's roles instead of a daily roll."""
        await self.send_rating(message, target, round(self.get_role_rating(target) * 100))
