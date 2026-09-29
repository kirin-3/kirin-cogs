"""Brat Rate Responder

Responds with a daily % rating for how brat a user is, with a quip for each tier.
"""

from .base_rate_responder import BaseRateResponder


class BratRate(BaseRateResponder):
    title = "❯ Brat Rate"
    description = "{target} is {rating}% brat"
    color = 0xFF1493
    bar_full = ("💢",)

    rating_overrides = {
        90: {
            "title": "❯ Menace to Society",
            "description": "{target} is {rating}% brat. Needs a firm hand, and knows it. 😈",
        },
        70: {
            "title": "❯ Certified Brat",
            "description": '{target} is {rating}% brat. Answers every order with "make me".',
        },
        40: {"title": "❯ Mouthy", "description": "{target} is {rating}% brat. Talks back when it counts."},
        15: {"title": "❯ Mostly Behaved", "description": "{target} is {rating}% brat. Pushes a button now and then."},
        0: {"title": "❯ Angel", "description": "{target} is {rating}% brat. Does as they're told. Suspicious."},
    }
