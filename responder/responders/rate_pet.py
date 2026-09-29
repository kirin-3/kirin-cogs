"""Pet Rate Responder

Responds with a daily % rating for how pet a user is, with a quip for each tier.
"""

from .base_rate_responder import BaseRateResponder


class PetRate(BaseRateResponder):
    title = "❯ Pet Rate"
    description = "{target} is {rating}% pet"
    color = 0xC8A2C8
    bar_full = ("🐾",)

    rating_overrides = {
        90: {
            "title": "❯ Good Pet",
            "description": "{target} is {rating}% pet. Collar on, tail wagging. Who's a good pet? 🐶",
        },
        70: {"title": "❯ Leash Ready", "description": "{target} is {rating}% pet. Would fetch if asked nicely."},
        40: {"title": "❯ Semi-Domesticated", "description": "{target} is {rating}% pet. Takes headpats, still bites."},
        15: {"title": "❯ Feral", "description": "{target} is {rating}% pet. Approach with treats."},
        0: {"title": "❯ Wild Animal", "description": "{target} is {rating}% pet. Cannot be tamed."},
    }
