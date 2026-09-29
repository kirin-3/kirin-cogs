"""Simp Rate Responder

Responds with a daily % rating for how simp a user is, with a quip for each tier.
"""

from .base_rate_responder import BaseRateResponder


class SimpRate(BaseRateResponder):
    title = "❯ Simp Rate"
    description = "{target} is {rating}% simp"
    color = 0xFF77A9
    bar_full = ("🥺",)

    rating_overrides = {
        90: {
            "title": "❯ Simp Emperor",
            "description": '{target} is {rating}% simp. Would hand over their whole wallet for a "ty".',
        },
        70: {
            "title": "❯ Professional Simp",
            "description": "{target} is {rating}% simp. Has notifications on for one specific person.",
        },
        40: {"title": "❯ Part-Time Simp", "description": "{target} is {rating}% simp. Simps on weekends only."},
        15: {"title": "❯ Barely Simping", "description": "{target} is {rating}% simp. A heart react here and there."},
        0: {"title": "❯ Unsimpable", "description": "{target} is {rating}% simp. Ice cold. Nobody gets through."},
    }
