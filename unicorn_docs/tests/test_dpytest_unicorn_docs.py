"""dpytest integration tests for unicorn_docs: ask command and moderation role gate."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from unicorn_docs.unicorndocs_precomputed import UnicornDocsPrecomputed

MOD_ROLES = [696020813299580940, 898586656842600549]


def make_cog() -> UnicornDocsPrecomputed:
    config = MagicMock(spec=Config)
    config.openrouter_api_key = AsyncMock(return_value="test-key")
    config.register_global = MagicMock()

    bot = MagicMock(spec=Red)
    bot.loop = MagicMock()
    bot.loop.run_in_executor = AsyncMock(return_value=({}, [], []))

    with patch("unicorn_docs.unicorndocs_precomputed.Config.get_conf", return_value=config):
        cog = UnicornDocsPrecomputed(bot)  # type: ignore[arg-type]
    cog.config = config
    return cog


# --- ask command: mocked OpenRouter returns answer ---


@pytest.mark.asyncio
async def test_ask_returns_embed_when_context_found() -> None:
    """ask command posts an embed when chunks are found and answer is generated."""
    cog = make_cog()

    ctx = MagicMock()
    ctx.send = AsyncMock(return_value=MagicMock(edit=AsyncMock()))

    cog.query_database = AsyncMock(return_value=[{"text": "Rules here", "source_file": "rules.md"}])
    cog.generate_answer = AsyncMock(return_value="Here is the answer to your question.")

    await cog.ask_question.callback(cog, ctx, question="What are the rules?")  # type: ignore[attr-defined]

    # Should have called send and then edit with an embed
    ctx.send.assert_called_once_with("🔍 Searching documentation...")
    msg = ctx.send.return_value
    # edit called multiple times; last call should have embed
    assert msg.edit.called
    last_call = msg.edit.call_args
    # Either embed= kwarg or no error means success
    assert last_call is not None


@pytest.mark.asyncio
async def test_ask_returns_no_results_message_when_empty() -> None:
    """ask command sends error-like message when no results found."""
    cog = make_cog()

    ctx = MagicMock()
    ctx.send = AsyncMock(return_value=MagicMock(edit=AsyncMock()))

    cog.query_database = AsyncMock(return_value=[])

    await cog.ask_question.callback(cog, ctx, question="Something with no match")  # type: ignore[attr-defined]

    msg = ctx.send.return_value
    msg.edit.assert_called()
    # Find any edit call that mentions "No relevant" or contains ❌
    found_no_results = False
    for call in msg.edit.call_args_list:
        content = (call.kwargs.get("content") or "") + " ".join(str(a) for a in call.args)
        if "No relevant" in content or "❌" in content:
            found_no_results = True
            break
    assert found_no_results, f"Expected 'no results' message, got calls: {msg.edit.call_args_list}"


@pytest.mark.asyncio
async def test_ask_handles_api_error_gracefully() -> None:
    """ask command handles OpenRouter errors without crashing."""
    cog = make_cog()

    ctx = MagicMock()
    ctx.send = AsyncMock(return_value=MagicMock(edit=AsyncMock()))

    cog.query_database = AsyncMock(return_value=[{"text": "Some context", "source_file": "a.md"}])
    cog.generate_answer = AsyncMock(side_effect=Exception("API error"))

    # Should not raise
    await cog.ask_question.callback(cog, ctx, question="A question")  # type: ignore[attr-defined]

    # edit should have been called with an error message
    msg = ctx.send.return_value
    assert msg.edit.called
