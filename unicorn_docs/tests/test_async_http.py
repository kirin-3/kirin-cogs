"""Tests for use of Red's shared asynchronous HTTP session."""

import aiohttp
import pytest


class _Response:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def json(self) -> dict:
        return {"choices": [{"message": {"content": "Documented answer"}}]}


@pytest.mark.asyncio
async def test_generate_answer_uses_bot_session_with_timeout(cog, bot_mock) -> None:
    bot_mock.session.post.return_value = _Response()
    chunks = [{"text": "A sufficiently long documentation excerpt " * 3, "source_file": "rules.md"}]

    answer = await cog.generate_answer("What is the rule?", chunks)

    assert answer == "Documented answer"
    bot_mock.session.post.assert_called_once()
    kwargs = bot_mock.session.post.call_args.kwargs
    assert isinstance(kwargs["timeout"], aiohttp.ClientTimeout)
    assert kwargs["timeout"].total == 60
