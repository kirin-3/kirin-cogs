from typing import Any, TypedDict, cast


class ProfileData(TypedDict, total=False):
    name: str
    age: int
    location: str
    gender: str
    sexuality: str
    role: str | None
    likes: str | None
    dislikes: str | None
    kinks: str | None
    limits: str | None
    about_me: str | None
    picture_url: str | None


# Constants for validation and UI
QUESTIONS = [
    {"id": "name", "label": "Name", "question": "What name do you go by?", "max_length": 50, "required": True},
    {"id": "age", "label": "Age", "question": "How old are you?", "max_length": 3, "required": True, "type": "int"},
    {
        "id": "location",
        "label": "Location",
        "question": "Where are you from? (Country or continent)",
        "max_length": 50,
        "required": True,
    },
    {
        "id": "gender",
        "label": "Gender",
        "question": "What gender do you identify as?",
        "max_length": 100,
        "required": True,
    },
    {
        "id": "sexuality",
        "label": "Sexuality",
        "question": "What is your sexuality?",
        "max_length": 100,
        "required": True,
    },
    {
        "id": "role",
        "label": "Role",
        "question": "What role do you prefer? (Sub/Dom/Switch)",
        "max_length": 100,
        "required": False,
    },
    {
        "id": "likes",
        "label": "Likes",
        "question": "What do you like in general? (Hobbies etc.)",
        "max_length": 1000,
        "required": False,
        "style": "long",
    },
    {
        "id": "dislikes",
        "label": "Dislikes",
        "question": "What do you dislike in general?",
        "max_length": 1000,
        "required": False,
        "style": "long",
    },
    {
        "id": "kinks",
        "label": "Kinks",
        "question": "What are your kinks?",
        "max_length": 1000,
        "required": False,
        "style": "long",
    },
    {
        "id": "limits",
        "label": "Limits",
        "question": "What are your limits?",
        "max_length": 1000,
        "required": False,
        "style": "long",
    },
    {
        "id": "about_me",
        "label": "About Me",
        "question": "Tell us a bit about yourself.",
        "max_length": 1000,
        "required": False,
        "style": "long",
    },
    {
        "id": "picture_url",
        "label": "Picture",
        "question": "Upload a picture of yourself.",
        "required": False,
        "type": "image",
    },
]

PROFILE_CHANNEL_ID = 686091267012296714
UNIQUE_ID = 0x6AFE8001

# Any positive age is accepted, including under 18: the post shows it so staff can act on it
AGE_RULE = "Age must be a positive whole number."

# Uploaded pictures are re-attached to the profile post, because a modal upload's link is temporary.
# Stored `picture_url` values with this prefix name the post's own attachment.
ATTACHMENT_PREFIX = "attachment://"
MAX_PICTURE_BYTES = 8 * 1024 * 1024
PICTURE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp"}


def parse_age(text: str) -> int | None:
    """Return the age typed into the builder, or None if it is not a positive whole number."""
    text = text.strip()
    if not text.isdecimal():
        return None
    age = int(text)
    return age if age > 0 else None


def is_valid_age(value: object) -> bool:
    """Whether a stored age is acceptable (older records may predate validation)."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def canonicalize_profile_data(data: dict) -> ProfileData:
    """Return a copy of profile data using only canonical field names.

    Legacy ``picture`` values are mapped to ``picture_url`` (never
    overwriting an existing canonical value) so old records display and
    migrate without user action.
    """
    canonical: dict[str, Any] = dict(data)
    legacy = canonical.get("picture")
    if isinstance(legacy, str) and legacy and not canonical.get("picture_url"):
        canonical["picture_url"] = legacy
    canonical.pop("picture", None)
    return cast(ProfileData, canonical)
