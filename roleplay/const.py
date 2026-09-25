"""Constants used throughout the package"""

import logging
from enum import Enum

from discord import Color

from . import __version__

# set logging level for package.
# Most common is logging.INFO or logging.DEBUG
LOGGER_LEVEL = logging.INFO

# limit on number of times a command can be used before cooldown these
# are defined in the module's global scope so they can be used as args
# for decorators or in other modules
COOLDOWN_RATE = 1
# command cooldown time in seconds
COOLDOWN_TIME = 120

# amount of time to wait for target member to consent in seconds
TIMEOUT = 60
# message to send if this happens
TIMEOUT_MESSAGE = "{user} took too long to respond. You can try again later."

# unique identifier for this cog
COG_IDENTIFIER = 842364413

# used to look up the default member when a command is invoked without a target member
# {serverID} : {userID}
DEFAULT_MEMBER_ID = {
    760220886460137513: 1314782522856570943,  # Ruffiana's Playground : Redbot
    684360255798509578: 695701050656817172,  # Unicornia Server : Unicorn Bot#0200
}

# seconds to delete any settings messages sent to user in private message short time
# would be used in any public-facing channel, to keep them from being too cluttered.
# long delete times would be used for ephemeral responses or private messages
SHORT_DELETE_TIME = 10
LONG_DELETE_TIME = 180

# Some constants used for consistency when making embeds
EMBED_LIST_LIMIT = 25
EMBED_COLOR = Color.from_str("#9401fe")
EMBED_FOOTER = f"Roleplay Cog ({__version__})"


class InteractionType(Enum):
    ACTIVE = "active"
    PASSIVE = "passive"


# default message for when a member denies consent for a roleplay action command.
REFUSAL_MESSAGE = "{target_member} does not wish to do that."
# message for when an owner(s) denies consent for an active command.
OWNER_REFUSAL_MESSAGE = "{owner} does not wish for {invoker_member} to do that to {target_member}."
# message to send when a member status is not "online" or "idle"
OFFLINE_MESSAGE = "It doesn't look like {user} is online. Try again later."

# This gets appended to the end of every consent question
CONSENT_QUESTION = "Do you consent?"

INSULTS = [
    "+1 Dimbo points.",
    "Get errored, idiot!",
    "smh",
    "Explain! As you would a child...",
    "Do you see how dumb that sounds?",
    "You have been banned from Roleplay!",
    ":facepalm:",
    "🤦‍♂️",
    "🙄",
    "🤔",
    "😅",
    "😜",
    "😆",
    "🥴",
]

# used to represent True and False in UI messages
TRUE_EMOJI = "✅"
FALSE_EMOJI = "❌"
