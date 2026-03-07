"""Unit tests for parse_ai_response in unimod."""

from unittest.mock import MagicMock, patch

import pytest

from unimod.unimod import AIAnalysisResult, UniMod


@pytest.fixture
def cog() -> UniMod:
    bot = MagicMock()
    with patch("unimod.unimod.Config.get_conf"), patch("discord.ext.tasks.Loop.start"):
        return UniMod(bot)  # type: ignore[arg-type]


# --- Helpers ---


def _clean_json(is_violation: bool = False, mid: int | str | None = None) -> str:
    return (
        '{"is_violation": '
        + str(is_violation).lower()
        + ', "confidence": 0.9, "violated_rules": [], "severity": null, '
        '"explanation": "All good.", "primary_message_id": ' + (f'"{mid}"' if isinstance(mid, str) else str(mid)) + "}"
    )


# --- Parametrized test cases ---

CLEAN_JSON = (
    '{"is_violation": false, "confidence": 0.1, "violated_rules": [], '
    '"severity": null, "explanation": "No issue.", "primary_message_id": null}'
)

FENCED_JSON = (
    "```json\n"
    '{"is_violation": true, "confidence": 0.95, "violated_rules": ["9.2"], '
    '"severity": "high", "explanation": "Violation found.", "primary_message_id": 123456789}\n'
    "```"
)

THINK_BLOCK_JSON = (
    "<think>Let me analyze this carefully.</think>\n"
    '{"is_violation": false, "confidence": 0.3, "violated_rules": [], '
    '"severity": null, "explanation": "After thinking, no violation.", "primary_message_id": null}'
)

STRING_MESSAGE_ID_JSON = (
    '{"is_violation": true, "confidence": 0.8, "violated_rules": ["1.1"], '
    '"severity": "low", "explanation": "Small issue.", "primary_message_id": "987654321"}'
)


@pytest.mark.parametrize(
    "raw,expected_violation,expected_msg_id",
    [
        (CLEAN_JSON, False, None),
        (FENCED_JSON, True, 123456789),
        (THINK_BLOCK_JSON, False, None),
        (STRING_MESSAGE_ID_JSON, True, 987654321),
    ],
    ids=["clean_json", "fenced_json", "think_block", "string_message_id"],
)
def test_parse_ai_response_valid(
    cog: UniMod,
    raw: str,
    expected_violation: bool,
    expected_msg_id: int | None,
) -> None:
    result = cog.parse_ai_response(raw)
    assert isinstance(result, AIAnalysisResult)
    assert result.is_violation is expected_violation
    assert result.primary_message_id == expected_msg_id


def test_parse_ai_response_malformed_raises(cog: UniMod) -> None:
    """Completely missing JSON should raise ValueError."""
    with pytest.raises(ValueError, match="No JSON object found"):
        cog.parse_ai_response("This is just plain text with no JSON at all.")


def test_parse_ai_response_invalid_json_raises(cog: UniMod) -> None:
    """Broken JSON (missing closing brace) - no matching JSON object so raises ValueError."""
    with pytest.raises(ValueError, match="No JSON object found"):
        cog.parse_ai_response('{"is_violation": true, "confidence": 0.9')


def test_parse_ai_response_string_message_id_coerced(cog: UniMod) -> None:
    """String primary_message_id must be coerced to int."""
    raw = (
        '{"is_violation": false, "confidence": 0.5, "violated_rules": [], '
        '"severity": null, "explanation": "ok", "primary_message_id": "111222333"}'
    )
    result = cog.parse_ai_response(raw)
    assert result.primary_message_id == 111222333


def test_parse_ai_response_invalid_severity_defaulted(cog: UniMod) -> None:
    """Unrecognized severity on a violation defaults to 'low'."""
    raw = (
        '{"is_violation": true, "confidence": 0.9, "violated_rules": ["1.0"], '
        '"severity": "extreme", "explanation": "Bad.", "primary_message_id": null}'
    )
    result = cog.parse_ai_response(raw)
    assert result.severity == "low"
