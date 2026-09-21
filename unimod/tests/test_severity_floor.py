"""Tests for the AI-visible rules, severity definitions, and the alert severity floor."""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unimod.unimod import AIAnalysisResult, BufferedMessage, UniMod


def test_prompt_excludes_9_1_and_9_2_and_defines_severity(cog: UniMod) -> None:
    prompt = cog._build_system_prompt()

    assert not re.search(r"^9\.[12] ", prompt, re.MULTILINE)
    assert '"9.2"' not in prompt
    for rule in ("9.3", "9.4", "9.5", "9.6", "9.7", "9.8"):
        assert re.search(rf"^{re.escape(rule)} ", prompt, re.MULTILINE), rule
    assert "## SEVERITY" in prompt
    for level in ("low", "medium", "high"):
        assert f'- "{level}":' in prompt


def _result(is_violation: bool, severity: str | None) -> AIAnalysisResult:
    return AIAnalysisResult(
        is_violation=is_violation,
        confidence=0.8,
        violated_rules=["7.1"] if is_violation else [],
        severity=severity,
        explanation="test",
        primary_message_id=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("floor", "is_violation", "severity", "should_alert"),
    [
        ("medium", True, "low", False),
        ("medium", True, "medium", True),
        ("medium", True, "high", True),
        ("medium", True, None, True),
        ("medium", False, None, False),
        ("low", True, "low", True),
    ],
)
async def test_severity_floor_gates_alerts(
    cog: UniMod,
    config_mock: MagicMock,
    floor: str,
    is_violation: bool,
    severity: str | None,
    should_alert: bool,
) -> None:
    config_mock.guild.side_effect = lambda _g: SimpleNamespace(min_severity=AsyncMock(return_value=floor))
    msg = BufferedMessage(1, 2, "user", "hi", "2026-09-21T00:00:00", 3, "chat", 4)
    channel = MagicMock(name="channel")

    with (
        patch.object(cog, "check_vader_scores", return_value=(True, -0.9, [])),
        patch.object(cog, "_analyze_with_ai", AsyncMock(return_value=_result(is_violation, severity))),
        patch.object(cog, "_send_alert", AsyncMock()) as send_alert,
    ):
        await cog._process_buffer(MagicMock(), channel, [msg])

    assert send_alert.await_count == (1 if should_alert else 0)
    assert cog.stats["violations_found"] == (1 if is_violation else 0)
