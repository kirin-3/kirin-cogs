"""Sus Rate Responder

Responds with a daily % rating for how sus a user is, with a quip for each tier.
"""

from .base_rate_responder import BaseRateResponder


class SusRate(BaseRateResponder):
    title = "❯ Sus Rate"
    description = "{target} is {rating}% sus"
    color = 0xC51111
    bar_full = ("🟥",)

    rating_overrides = {
        90: {
            "title": "❯ Emergency Meeting",
            "description": "{target} is {rating}% sus. Seen venting. Vote them out. 🔪",
        },
        70: {"title": "❯ Very Sus", "description": "{target} is {rating}% sus. Was not in electrical doing tasks."},
        40: {"title": "❯ Kinda Sus", "description": "{target} is {rating}% sus. Something's off, can't prove it."},
        15: {"title": "❯ Probably Fine", "description": "{target} is {rating}% sus. Did their tasks. Mostly."},
        0: {"title": "❯ Crewmate", "description": "{target} is {rating}% sus. Clean. Hard clear."},
    }
