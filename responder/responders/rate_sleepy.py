"""Sleepy Rate Responder

Responds with a daily % rating for how sleepy a user is, with a quip for each tier.
"""

from .base_rate_responder import BaseRateResponder


class SleepyRate(BaseRateResponder):
    title = "❯ Sleepy Rate"
    description = "{target} is {rating}% sleepy"
    color = 0x5C6BC0
    bar_full = ("💤",)

    rating_overrides = {
        90: {
            "title": "❯ Comatose",
            "description": "{target} is {rating}% sleepy. Fell asleep mid-sentence. Tuck them in. 🛏️",
        },
        70: {"title": "❯ Very Eepy", "description": "{target} is {rating}% sleepy. Needs a nap right now."},
        40: {"title": "❯ Yawning", "description": "{target} is {rating}% sleepy. Running on coffee and spite."},
        15: {"title": "❯ Awake-ish", "description": "{target} is {rating}% sleepy. Awake, technically."},
        0: {"title": "❯ Wired", "description": "{target} is {rating}% sleepy. Wide awake, vibrating slightly."},
    }
