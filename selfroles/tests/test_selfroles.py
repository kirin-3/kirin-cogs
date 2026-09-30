"""The self-role helpers: emoji and banner checks, and reading malformed Config."""

from functools import partial
from types import SimpleNamespace
from typing import Any, cast

import pytest

from selfroles.selfroles import (
    MAX_NOTE,
    MAX_OPTIONS,
    SelfRoles,
    banner_type,
    clean_category,
    clean_note,
    is_unicode_emoji,
    limit_text,
    plain_note,
)


@pytest.mark.parametrize("text", ["❤️", "🤍", "🏳️‍⚧️", "🇪🇺", "1️⃣", "*️⃣", "♀", "👩🏽", "🛋️"])
def test_emoji_are_accepted(text: str) -> None:
    assert is_unicode_emoji(text)


@pytest.mark.parametrize("text", ["", "abc", "1", "#", "<3", "❤️ love", ":heart:", "🍹" * 20])
def test_text_that_is_not_an_emoji_is_refused(text: str) -> None:
    assert not is_unicode_emoji(text)


def test_banners_are_recognised_by_content() -> None:
    assert banner_type(b"\x89PNG\r\n\x1a\n...") == "png"
    assert banner_type(b"\xff\xd8\xff\xe0...") == "jpg"
    assert banner_type(b"GIF89a...") == "gif"
    assert banner_type(b"RIFF\0\0\0\0WEBPVP8 ") == "webp"
    assert banner_type(b"<svg></svg>") is None


def test_malformed_config_is_cleaned_up() -> None:
    assert clean_category(None) is None
    assert clean_category({"max": 3}) is None
    assert clean_category({"name": "Age", "max": True, "roles": "nope", "banner": "../../x", "channel_id": -1}) == {
        "name": "Age",
        "max": 1,
        "roles": [],
        "channel_id": None,
        "message_id": None,
        "banner": None,
    }
    raw = {
        "name": "Age",
        "max": MAX_OPTIONS + 1,
        "roles": [{"id": 5, "emoji": 3, "note": None}, {"id": 5}, {"id": "6"}, "x", {"id": 7, "note": "n" * 150}],
    }
    category = clean_category(raw)
    assert category is not None and category["max"] == 1
    assert category["roles"] == [{"id": 5, "emoji": "", "note": ""}, {"id": 7, "emoji": "", "note": "n" * MAX_NOTE}]


def test_notes_are_one_line_and_at_most_100_characters() -> None:
    assert clean_note("  Opens\n the   Chastity channel ") == "Opens the Chastity channel"
    assert clean_note("") == ""
    assert clean_note("x" * MAX_NOTE) == "x" * MAX_NOTE
    with pytest.raises(ValueError, match="at most 100"):
        clean_note("x" * (MAX_NOTE + 1))


def test_the_dropdown_shows_channel_mentions_as_names() -> None:
    little = SimpleNamespace(name="little-space")
    guild = cast(Any, SimpleNamespace(get_channel_or_thread=lambda i: little if i == 123456789012345678 else None))

    assert plain_note(guild, "Opens <#123456789012345678>") == "Opens #little-space"
    assert plain_note(guild, "Opens <#999999999999999999>") == "Opens #deleted-channel"
    assert plain_note(guild, "Ping me for **events**") == "Ping me for **events**"


def test_custom_emoji_by_name_or_code_must_be_one_the_bot_can_use() -> None:
    class _Emoji:
        name = "bi"

        def __str__(self) -> str:
            return "<:bi:123456789012345678>"

    guild = SimpleNamespace(emojis=[_Emoji()])
    bot = SimpleNamespace(get_emoji=lambda emoji_id: object() if emoji_id == 123456789012345678 else None)
    clean = partial(SelfRoles.clean_emoji, cast(Any, SimpleNamespace(bot=bot)), cast(Any, guild))

    assert clean(" :bi: ") == "<:bi:123456789012345678>"
    assert clean("<a:bi:123456789012345678>") == "<a:bi:123456789012345678>"
    assert clean("") == "" and clean("❤️") == "❤️"
    with pytest.raises(ValueError, match="no emoji called :nope:"):
        clean(":nope:")
    with pytest.raises(ValueError, match="can't use that emoji"):
        clean("<:xy:999999999999999999>")
    with pytest.raises(ValueError, match="isn't an emoji"):
        clean("hello")


def test_the_limit_reads_naturally() -> None:
    assert limit_text(1) == "Pick one."
    assert limit_text(3) == "Pick up to 3."
