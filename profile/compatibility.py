"""Compatibility scores for ``[p]compat``, from profile answers and self-assigned roles.

Only the percentage and a verdict are ever shown, never which kinks, limits or interests matched.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

# Kink roles count as that kink, and sharing the role itself counts double
KINK_ROLES = {
    903170628213944321: "pet play",
    696048923546091575: "hypnosis",
    696048913022713907: "age play",
    696048928415678556: "furry",
    696048918248554627: "free use",
    708022864577560629: "attention whore",
}
SWITCH_ROLE = 686097307070103648
# The same weights as responder/responders/rate_dom.py; dom, domme and submissive are among them
DOM_ROLES = {
    1329908395578495068: 1.00,
    686097057190379537: 1.00,
    686097106083119115: 1.00,
    694788857371033640: 1.00,
    694788859015462923: 0.25,
    694788860760031243: 0.25,
    694789801353805862: 0.25,
    694789803153162290: 0.25,
    694790101095546890: 0.25,
    694790104044142612: 1.00,
    694790108230189087: 0.25,
    686098541831127048: 0.10,
    811471307106942996: 0.50,
}
SUB_ROLES = {
    1329908302187855972: 1.00,
    686097362107498504: 1.00,
    768103786119823380: 0.75,
    768103783498121296: 0.75,
    694788843207131246: 1.00,
    694788849020305451: 0.75,
    694788851155337236: 0.20,
    694788853419999352: 0.20,
    694788854942531607: 0.50,
    1074675006006644736: 0.05,
    696082750775492688: 0.20,
    694790765460848701: 1.00,
    696048918248554627: 1.00,
    708022873058574396: 0.25,
    686098506834116620: 0.05,
    686098381214711837: 1.00,
}

# Each kink and the ways members write it in their Kinks and Limits answers
KINKS = {
    "age play": r"age ?play|ddl[gb]|mdl[gb]|cglre|cgl|little ?space",
    "anal": r"anal",
    "attention whore": r"attention(?: whore)?",
    "bdsm": r"bdsm",
    "bimbofication": r"bimbo\w*",
    "blackmail": r"blackmail",
    "blood": r"blood(?: ?play)?",
    "bondage": r"bondage|rope\w*|shibari|tied up|restrain\w*",
    "breeding": r"breed\w*",
    "cbt": r"cbt|ball ?busting",
    "cei": r"cei",
    "chastity": r"chastity|cage|caged",
    "choking": r"chok\w*|breath ?play",
    "cnc": r"cnc|consensual non[ -]?consent|non[ -]?con|rape ?play",
    "cuckolding": r"cuck\w*",
    "cum play": r"cum ?play",
    "degradation": r"degrad\w*",
    "diapers": r"diapers?|abdl",
    "dirty talk": r"dirty talk\w*",
    "discipline": r"disciplin\w*",
    "edging": r"edging|edge",
    "exhibitionism": r"exhibition\w*|public (?:play|sex)",
    "face sitting": r"face ?sitting",
    "feet": r"feet|foot|toes",
    "femboys": r"femboys?",
    "femdom": r"femdom",
    "feminization": r"femini[sz]\w*|sissif\w*|sissy|sissies",
    "findom": r"findom|financial domination",
    "fisting": r"fisting",
    "free use": r"free ?use",
    "furry": r"furr(?:y|ies)|fursuit\w*",
    "gore": r"gore",
    "humiliation": r"humiliat\w*",
    "hypnosis": r"hypno\w*|trance",
    "impact play": r"impact(?: play)?|paddl\w*|flogg\w*|whip\w*|caning",
    "inflation": r"inflation",
    "joi": r"joi|jerk off instructions?",
    "knife play": r"knife(?: ?play)?|knives",
    "latex": r"latex|rubber",
    "medical": r"medical",
    "misgendering": r"misgender\w*",
    "needles": r"needles?",
    "nipple play": r"nipples?(?: play)?",
    "objectification": r"objectif\w*",
    "orgasm control": r"orgasm control|orgasm denial|denial|ruin(?:ed|ing)? orgasms?",
    "overstimulation": r"over ?-?stim\w*",
    "pain play": r"pain(?: ?play)?|masochis\w*|sadis\w*|sadomasochis\w*",
    "pegging": r"pegg\w*|strap-?on",
    "pet play": r"pet ?play|pup(?:py)? ?play|kitten ?play|puppy|kitten|collars?|leash\w*",
    "praise": r"praise|good (?:girl|boy)",
    "race play": r"race ?play",
    "rough sex": r"rough(?: sex)?",
    "roleplay": r"role ?play\w*|rp",
    "scat": r"scat|poop|toilet ?play",
    "sensory play": r"sensory \w+|blindfold\w*",
    "somnophilia": r"somno\w*|sleep ?play",
    "sounding": r"sounding",
    "spanking": r"spank\w*",
    "sph": r"sph|small penis humiliation",
    "spit": r"spit\w*",
    "teasing": r"teas(?:e|ing)",
    "tickling": r"tickl\w*",
    "toys": r"toys?|vibrators?|dildos?|plugs?",
    "tpe": r"tpe|total power exchange",
    "vomit": r"vomit\w*|puke|emeto\w*",
    "vore": r"vore",
    "voyeurism": r"voyeur\w*",
    "watersports": r"water ?sports|piss\w*|pee|urine|golden showers?",
    "wax play": r"wax(?: play)?",
    "worship": r"worship\w*",
}
_KINK_PATTERNS = {name: re.compile(rf"\b(?:{pattern})\b") for name, pattern in KINKS.items()}

# The Role answer: "sub", "switch leaning dom", "domme", ...
_DOM_TEXT = re.compile(r"\b(?:dom|domme|dominant|dommy|top|owner|master|mistress|sadist|daddy|mommy)\b")
_SUB_TEXT = re.compile(r"\b(?:sub|subby|submissive|bottom|bottem|slave|pet|little|sissy|masochist|brat)\b")
_SWITCH_TEXT = re.compile(r"\b(?:switch\w*|verse|vers)\b")

# Words in the Likes answer that say nothing about the hobby itself
_FILLER = frozenset({
    "about", "also", "always", "anything", "being", "doing", "enjoy", "enjoying", "especially", "everything",
    "favorite", "favourite", "from", "general", "going", "good", "have", "hobbie", "hobby", "into", "just", "kind",
    "kinds", "like", "likes", "listening", "lots", "love", "loves", "mainly", "make", "making", "more", "most",
    "mostly", "much", "other", "people", "playing", "really", "some", "sometimes", "spending", "stuff", "that",
    "thing", "things", "this", "time", "usually", "very", "watching", "well", "what", "when", "with",
})  # fmt: skip
_SAME_INTEREST: dict[str, str] = {"gaming": "game", "videogame": "game", "film": "movie"}

VERDICTS = [
    (85, "Soulmates. Get a room. 💞"),
    (70, "A match made in the dungeon. ⛓️"),
    (55, "Real chemistry here. Worth a DM. 😏"),
    (40, "Could work, with some negotiation. 🤝"),
    (25, "Friends first, maybe. 🙂"),
    (10, "A rough match, and not the fun kind. 😬"),
    (0, "Hard limits all round. Better as strangers. 🚫"),
]


@dataclass(frozen=True)
class Side:
    """What one member brings to the comparison."""

    lean: float | None  # -1 submissive to 1 dominant, or None when neither their roles nor their profile say
    switch: bool
    kinks: frozenset[str]
    kink_roles: frozenset[str]
    limits: frozenset[str]
    interests: frozenset[str]

    @property
    def known(self) -> bool:
        return self.lean is not None or bool(self.kinks or self.interests)


def kinks_in(text: object) -> frozenset[str]:
    """The known kinks named in a free-text answer."""
    if not isinstance(text, str):
        return frozenset()
    text = text.lower()
    return frozenset(name for name, pattern in _KINK_PATTERNS.items() if pattern.search(text))


def interests_in(text: object) -> frozenset[str]:
    """The hobby words in the Likes answer, roughly singular."""
    if not isinstance(text, str):
        return frozenset()
    words = (word.removesuffix("s") for word in re.findall(r"[a-z]{4,}", text.lower()))
    return frozenset(_SAME_INTEREST.get(word) or word for word in words if word not in _FILLER)


def _text_lean(text: object) -> tuple[float | None, bool]:
    if not isinstance(text, str):
        return None, False
    text = text.lower()
    dom, sub, switch = (bool(pattern.search(text)) for pattern in (_DOM_TEXT, _SUB_TEXT, _SWITCH_TEXT))
    if not (dom or sub or switch):
        return None, False
    return float(dom - sub), switch


def side(profile: object, role_ids: Collection[int]) -> Side:
    """Read a member's stored profile answers (possibly empty or malformed) and role IDs."""
    data: dict[str, Any] = profile if isinstance(profile, dict) else {}
    ids = set(role_ids)

    leans = []
    rating = sum(w for r, w in DOM_ROLES.items() if r in ids) - sum(w for r, w in SUB_ROLES.items() if r in ids)
    role_switch = SWITCH_ROLE in ids
    if rating or role_switch:
        leans.append(max(-1.0, min(1.0, rating)))
    text_lean, text_switch = _text_lean(data.get("role"))
    if text_lean is not None:
        leans.append(text_lean)
    switch = role_switch or text_switch
    lean = sum(leans) / len(leans) if leans else None
    if lean is not None and switch:
        lean /= 2

    kink_roles = frozenset(KINK_ROLES[r] for r in ids if r in KINK_ROLES)
    return Side(
        lean=lean,
        switch=switch,
        kinks=kinks_in(data.get("kinks")) | kink_roles,
        kink_roles=kink_roles,
        limits=kinks_in(data.get("limits")),
        interests=interests_in(data.get("likes")),
    )


def score(a: Side, b: Side) -> int | None:
    """0 to 100, or None when the two share nothing that can be compared."""
    # Tuned on the live profiles so random pairs spread out over roughly 10 to 85
    parts: list[tuple[float, float]] = []  # (weight, 0-1 value)
    if a.lean is not None and b.lean is not None:
        dynamic = 0.15 + 0.85 * (1 - a.lean * b.lean) / 2  # dom with sub is 1, two doms or two subs 0.15
        if a.switch or b.switch:
            dynamic = max(dynamic, 0.75)
        parts.append((0.35, dynamic))
    if a.kinks and b.kinks:
        shared = len(a.kinks & b.kinks) + len(a.kink_roles & b.kink_roles)
        parts.append((0.45, 1 - 0.5**shared))
    if a.interests and b.interests:
        parts.append((0.2, 1 - 0.6 ** len(a.interests & b.interests)))
    if not parts:
        return None

    # A neutral 50% weighs in too, so one lone match or mismatch can't decide the whole score
    value = (sum(weight * v for weight, v in parts) + 0.15 * 0.5) / (sum(weight for weight, _ in parts) + 0.15)
    clashes = len(a.kinks & b.limits) + len(b.kinks & a.limits)
    return max(0, round(100 * value) - 15 * clashes)


def verdict(percent: int) -> str:
    return next(text for floor, text in VERDICTS if percent >= floor)


def bar(percent: int) -> str:
    filled = round(percent / 10)
    return "▰" * filled + "▱" * (10 - filled)
