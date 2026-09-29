"""Gremlin Rate Responder

Responds with a daily % rating for how gremlin a user is, with a quip for each tier.
"""

from .base_rate_responder import BaseRateResponder


class GremlinRate(BaseRateResponder):
    title = "❯ Gremlin Rate"
    description = "{target} is {rating}% gremlin"
    color = 0x6B8E23
    bar_full = ("🟩",)

    rating_overrides = {
        90: {"title": "❯ Feral Gremlin", "description": "{target} is {rating}% gremlin. Up at 3am chewing cables. 🔌"},
        70: {
            "title": "❯ Chaos Goblin",
            "description": "{target} is {rating}% gremlin. Hoards shiny things and snacks.",
        },
        40: {"title": "❯ Mischievous", "description": "{target} is {rating}% gremlin. Don't feed them after midnight."},
        15: {"title": "❯ Mostly Civilised", "description": "{target} is {rating}% gremlin. Only a little bitey."},
        0: {"title": "❯ Model Citizen", "description": "{target} is {rating}% gremlin. Pays taxes. Makes the bed."},
    }
