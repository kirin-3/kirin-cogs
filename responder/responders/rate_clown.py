"""Clown Rate Responder

Responds with a daily % rating for how clown a user is, with a quip for each tier.
"""

from .base_rate_responder import BaseRateResponder


class ClownRate(BaseRateResponder):
    title = "❯ Clown Rate"
    description = "{target} is {rating}% clown"
    color = 0xFFD000
    bar_full = ("🤡",)

    rating_overrides = {
        90: {
            "title": "❯ The Whole Circus",
            "description": "{target} is {rating}% clown. Not a clown, the entire circus. 🎪",
        },
        70: {"title": "❯ Honk Honk", "description": "{target} is {rating}% clown. The makeup's already on."},
        40: {
            "title": "❯ Clown in Training",
            "description": "{target} is {rating}% clown. Owns the red nose, doesn't wear it yet.",
        },
        15: {"title": "❯ Occasional Goof", "description": "{target} is {rating}% clown. A goof now and then."},
        0: {"title": "❯ Dead Serious", "description": "{target} is {rating}% clown. Has never told a joke."},
    }
