"""Tests for the alert embed limits and the `[p]unimod last` command."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unimod.unimod import EMBED_FIELD_LIMIT, BufferedMessage, UniMod


def test_long_explanation_fits_alert_embed(cog: UniMod) -> None:
    """A long AI explanation must not push the alert past Discord's embed limits."""
    raw = (
        '{"is_violation": true, "confidence": 0.9, "violated_rules": ["7.1"], "severity": "high", '
        f'"explanation": "{"x" * 5000}", "primary_message_id": 42}}'
    )
    result = cog.parse_ai_response(raw)
    guild = MagicMock(id=1)
    guild.name = "Guild"
    channel = MagicMock(id=2)
    channel.name = "chat"
    messages = [BufferedMessage(i, 3, "user", "y" * 500, "2026-09-24T00:00:00", 2, "chat", 1) for i in range(20)]

    embed = cog._build_alert_embed(guild, channel, messages, result)

    explanation = next(field for field in embed.fields if field.name == "Explanation")
    assert explanation.value is not None
    assert len(explanation.value) == EMBED_FIELD_LIMIT
    assert explanation.value.endswith("...")
    assert all(len(field.value or "") <= EMBED_FIELD_LIMIT for field in embed.fields)
    assert len(embed) <= 6000


def _dm_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.guild = None
    ctx.send = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_last_works_without_ever_enabling_diagnostics(cog: UniMod) -> None:
    """`last` used to raise AttributeError because diagnostic_mode was never initialised."""
    assert cog.diagnostic_mode is False
    cog._last_ai_response = '{"is_violation": false}'
    ctx = _dm_ctx()

    await cog.view_last_response.callback(cog, ctx)  # type: ignore[arg-type]

    ctx.send.assert_awaited_once()
    assert '{"is_violation": false}' in ctx.send.await_args.args[0]


@pytest.mark.asyncio
async def test_last_with_nothing_recorded(cog: UniMod) -> None:
    ctx = _dm_ctx()

    await cog.view_last_response.callback(cog, ctx)  # type: ignore[arg-type]

    ctx.send.assert_awaited_once_with("❌ No AI response has been recorded yet.")


@pytest.mark.asyncio
async def test_last_truncates_long_errors(cog: UniMod) -> None:
    """An HTML error page from the API must not make the reply exceed 2,000 characters."""
    cog._last_ai_error = "API Error 502: " + "<html>" * 1000
    ctx = _dm_ctx()

    await cog.view_last_response.callback(cog, ctx)  # type: ignore[arg-type]

    sent = ctx.send.await_args.args[0]
    assert sent.startswith("❌ Last AI request failed:")
    assert len(sent) <= 2000
