"""Cute Rate Responder

All users are 100% cute, except for Ruffiana.
"""

from .. import const
from .base_rate_responder import BaseRateResponder


class CuteRate(BaseRateResponder):
    title = "❯ Cute Rate"
    description = "{target} is 100% Cute"

    user_overrides = {
        const.RUFFIANA_ID: {
            "description": [
                "I'm sure {target} has a great...personality...",
                "{target}...?\n\nCute??..No.\n\nSorry, but no.",
                "{target}??\n\nLOL!!",
                "{target} is definitely *not* cute!",
            ]
        }
    }
