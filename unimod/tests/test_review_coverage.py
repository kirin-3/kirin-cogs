"""Neutral under-18 age claims reach the AI, and a review that fails still alerts staff."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nltk.sentiment.vader import SentimentIntensityAnalyzer

from unimod.unimod import BufferedMessage, UniMod, mentions_minor_age


def _msg(content: str) -> BufferedMessage:
    return BufferedMessage(1, 2, "user", content, "2026-09-21T00:00:00+00:00", 3, "chat", 4)


@pytest.mark.parametrize(
    "text",
    [
        "lol I'm 16",
        "im 17 btw",
        "I’m only 15",  # noqa: RUF001
        "I am just 16 years old",
        "17yo here",
        "she's 16 y/o",
        "I'm still in high school",
        "turning 17 next week",
    ],
)
def test_under_18_age_claims_are_caught(text: str) -> None:
    assert mentions_minor_age(text)


@pytest.mark.parametrize(
    "text",
    [
        "I'm 19",
        "I'm 25 and tired",
        "I'm 16 minutes away",
        "I'm 160cm tall",
        "I have 16 plushies",
        "I finished high school years ago",
    ],
)
def test_adult_and_unrelated_numbers_are_not_caught(text: str) -> None:
    assert not mentions_minor_age(text)


def test_a_neutral_age_claim_is_reviewed_straight_away(cog: UniMod) -> None:
    cog.vader_analyzer = SentimentIntensityAnalyzer()
    message = _msg("lol I'm 16")

    should_trigger, _score, urgent = cog._vader_check_single(message, -0.5)

    assert should_trigger and urgent
    assert cog.check_vader_scores([_msg("hi"), message], -0.5)[0]


class _Response:
    status = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    async def __aenter__(self) -> "_Response":
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def json(self) -> dict[str, Any]:
        return self._body


class _Session:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body
        self.payload: dict[str, Any] = {}

    async def __aenter__(self) -> "_Session":
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    def post(self, *_args: object, json: dict[str, Any], **_kwargs: object) -> _Response:
        self.payload = json
        return _Response(self.body)


@pytest.mark.asyncio
async def test_an_empty_reply_is_an_error_and_the_model_gets_room_to_think(cog: UniMod) -> None:
    session = _Session({"choices": [{"message": {"content": None}, "finish_reason": "length"}]})

    with (
        patch("unimod.unimod.aiohttp.ClientSession", return_value=session),
        pytest.raises(RuntimeError, match="Empty AI reply"),
    ):
        await cog._analyze_with_ai("system", "user")

    assert session.payload["max_tokens"] == 10000
    assert cog._last_ai_error is not None
    assert "Empty AI reply (finish_reason: length)" in cog._last_ai_error


@pytest.mark.asyncio
async def test_a_failed_review_alerts_staff(cog: UniMod) -> None:
    channel = MagicMock(id=3)
    channel.name = "chat"
    guild = MagicMock(id=4)
    guild.name = "Unicornia"
    cog.vader_analyzer = SentimentIntensityAnalyzer()

    with (
        patch.object(cog, "_analyze_with_ai", AsyncMock(side_effect=ValueError("Empty AI reply"))),
        patch.object(cog, "_deliver_alert", AsyncMock()) as deliver,
    ):
        await cog._process_buffer(guild, channel, [_msg("lol I'm 16")])

    deliver.assert_awaited_once()
    embed = deliver.call_args.args[1]
    assert embed.title == "⚠️ Flagged Conversation Not Reviewed"
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Reason"] == "Empty AI reply"
    assert "lol I'm 16" in fields["Recent Context"]
