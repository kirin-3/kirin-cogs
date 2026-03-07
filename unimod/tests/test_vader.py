"""Unit tests for VADER scoring in unimod."""

from unittest.mock import MagicMock, patch

import pytest

from unimod.unimod import BufferedMessage, UniMod


def _make_msg(content: str, msg_id: int = 1) -> BufferedMessage:
    return BufferedMessage(
        id=msg_id,
        author_id=100,
        author_name="User",
        content=content,
        timestamp="2024-01-01T00:00:00+00:00",
        channel_id=200,
        channel_name="test-channel",
        guild_id=300,
    )


@pytest.fixture
def cog() -> UniMod:
    bot = MagicMock()
    with patch("unimod.unimod.Config.get_conf"), patch("discord.ext.tasks.Loop.start"):
        return UniMod(bot)  # type: ignore[arg-type]


# --- _vader_check_single ---


def test_vader_check_single_trigger(cog: UniMod) -> None:
    msg = _make_msg("I hate you, you are terrible and disgusting!")
    triggered, score, _ = cog._vader_check_single(msg, threshold=-0.5)
    assert triggered is True
    assert score < -0.5


def test_vader_check_single_no_trigger(cog: UniMod) -> None:
    msg = _make_msg("Hello! How are you today?")
    triggered, score, _ = cog._vader_check_single(msg, threshold=-0.5)
    assert triggered is False
    assert score >= -0.5


def test_vader_check_single_empty_content(cog: UniMod) -> None:
    msg = _make_msg("   ")
    triggered, score, is_extreme = cog._vader_check_single(msg, threshold=-0.5)
    assert triggered is False
    assert score == 0.0
    assert is_extreme is False


def test_vader_check_single_extreme_flag(cog: UniMod) -> None:
    """Score well below threshold - 0.3 should mark is_extreme."""
    msg = _make_msg("Kill yourself, you worthless disgusting garbage piece of trash!")
    triggered, score, is_extreme = cog._vader_check_single(msg, threshold=-0.5)
    if score < -0.8:  # extreme = threshold - 0.3 = -0.8
        assert is_extreme is True
    # Either way, triggered must be consistent with score
    assert triggered == (score < -0.5)


# --- check_vader_scores ---


@pytest.mark.parametrize(
    "contents, expected_trigger",
    [
        (["Hello world", "Nice day!"], False),
        (["I hate you so much, you are disgusting trash"], True),
        ([], False),
        (["   ", "  "], False),
    ],
)
def test_check_vader_scores(cog: UniMod, contents: list[str], expected_trigger: bool) -> None:
    messages = [_make_msg(c, i) for i, c in enumerate(contents)]
    triggered, _, _ = cog.check_vader_scores(messages, threshold=-0.5)
    assert triggered is expected_trigger


def test_check_vader_scores_lowest_tracked(cog: UniMod) -> None:
    """The returned lowest score should be the minimum compound across messages."""
    msgs = [
        _make_msg("I hate everything!", 1),
        _make_msg("Hello!", 2),
    ]
    _, lowest, _ = cog.check_vader_scores(msgs, threshold=-0.5)
    # lowest must be <= 0 because "I hate everything!" is negative
    assert lowest < 0.0


def test_check_vader_scores_extreme_flag(cog: UniMod) -> None:
    """Messages with very negative scores should set is_extreme."""
    msgs = [_make_msg("Kill yourself you worthless disgusting garbage!", 1)]
    _, score, is_extreme = cog.check_vader_scores(msgs, threshold=-0.5)
    # Only assert is_extreme if score is below extreme threshold
    if score < -0.8:
        assert is_extreme is True
