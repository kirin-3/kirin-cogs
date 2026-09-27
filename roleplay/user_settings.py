USER_SETTINGS = {
    "owners": {
        "aliases": ["owner"],
        "default": [],
        "label": "Owner",
        "description": "Always consent to any action from your owner. Owners are also asked for consent instead of you.",
        "emoji": "👑",
        "permission": {
            "required": True,
            "permission_ask": "{target}, {author} would like you to be their Owner. Do you agree?",
            "permission_accept": "{target} is now your owner, {author}.",
            "permission_deny": "Sorry, {author}. {target} declined to become your Owner.",
        },
    },
    "allowed": {
        "aliases": ["allow", "approved", "approve"],
        "default": [],
        "label": "Allowed Users",
        "description": "Always consent to any action from members in your allowed list.",
        "emoji": "✅",
    },
    "blocked": {
        "aliases": ["block"],
        "default": [],
        "label": "Blocked Users",
        "description": "Ignore any roleplay command from members in your blocked list.",
        "emoji": "🚫",
    },
    # "keyholder": {
    #     "default": [],
    #     "label": "Keyholder",
    #     "description": "Your keyholder is responsible for managing your chastity.",
    #     "emoji": "🗝️",
    # },
    "selective": {
        "default": False,
        "label": "Selective",
        "description": "Always reject roleplay commands from any user not in your allowed list.",
        "emoji": "🛡️",
    },
    "public": {
        "default": False,
        "label": "Public Use Slut",
        "description": "Always consent to any action *from* a member (except those in your blocked list.)",
        "emoji": "🆓",
    },
    "servant": {
        "default": False,
        "label": "Servant",
        "description": "Always consent to any request to perform an action *on* a member (except those in your blocked list.)",
        "emoji": "🧹",
    },
    "untracked": {
        "default": False,
        "label": "Untracked Member",
        "description": "Don't count your roleplay actions in the stats, and delete what was already counted.",
        "emoji": "🙈",
    },
    # "chastity": {
    #     "default : False",
    #     "label": "Chastity",
    #     "description": "Properties for chastity.",
    #     "emoji": "🔒"
    #     },
}
