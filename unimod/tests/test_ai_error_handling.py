"""Regression tests for UniMod AI error handling."""

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from unimod.unimod import UniMod


async def sse(*chunks: dict[str, Any]) -> AsyncIterator[bytes]:
    """Yield chunks the way an OpenAI-style stream sends them, keep-alive comment and all."""
    yield b": keep-alive\n"
    for chunk in chunks:
        yield f"data: {json.dumps(chunk)}\n".encode()
        yield b"\n"
    yield b"data: [DONE]\n"


class FakeErrorResponse:
    """Minimal aiohttp-like response object for non-200 tests."""

    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body
        self.request_info = SimpleNamespace(real_url="https://integrate.api.nvidia.com/v1/chat/completions")
        self.history: tuple[object, ...] = ()

    async def __aenter__(self) -> "FakeErrorResponse":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    async def text(self) -> str:
        return self._body

    async def json(self) -> dict[str, object]:
        raise AssertionError("json() should not be called for non-200 responses")


class FakeSession:
    """Minimal aiohttp-like client session for response tests."""

    def __init__(self, response: FakeErrorResponse):
        self._response = response

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False

    def post(self, *args: object, **kwargs: object) -> FakeErrorResponse:
        return self._response


@pytest.mark.asyncio
async def test_when_every_model_fails_the_error_names_each_one(cog: UniMod) -> None:
    response = FakeErrorResponse(status=500, body="upstream bad request")

    with patch("unimod.unimod.aiohttp.ClientSession", return_value=FakeSession(response)):
        with pytest.raises(RuntimeError, match="Every AI model failed") as exc_info:
            await cog._analyze_with_ai("system prompt", "user prompt")

    exc_text = str(exc_info.value)
    assert "z-ai/glm-5.3: 500, message='NVIDIA NIM API Error 500: upstream bad request'" in exc_text
    assert "gemini-3.8-flash: 500, message='Google AI Studio API Error 500" in exc_text
    assert cog._last_ai_error is not None
    assert len(cog._last_ai_error.splitlines()) == len(UniMod.AI_PROVIDERS)


class FakeOkResponse(FakeErrorResponse):
    def __init__(self) -> None:
        super().__init__(status=200, body="")

    @property
    def content(self) -> AsyncIterator[bytes]:
        return sse(
            {"choices": [{"delta": {"reasoning_content": "hmm"}}]},
            {"choices": [{"delta": {"content": '{"is_violation": false, '}}]},
            {"choices": [{"delta": {"content": '"confidence": 0.9}'}, "finish_reason": "stop"}]},
        )


class FallbackSession(FakeSession):
    """Fails with a 504 for the first model and answers for every other one."""

    def __init__(self) -> None:
        self.models: list[str] = []

    def post(self, *args: object, **kwargs: Any) -> FakeErrorResponse:
        self.models.append(kwargs["json"]["model"])
        return FakeErrorResponse(504, "") if len(self.models) == 1 else FakeOkResponse()


@pytest.mark.asyncio
async def test_a_failed_model_falls_back_to_the_next_one(cog: UniMod) -> None:
    session = FallbackSession()

    with patch("unimod.unimod.aiohttp.ClientSession", return_value=session):
        result = await cog._analyze_with_ai("system prompt", "user prompt")

    assert result.is_violation is False
    assert session.models == ["z-ai/glm-5.3", "deepseek-ai/deepseek-v4.1-flash"]
    assert cog._last_ai_error is None


@pytest.mark.asyncio
async def test_a_provider_without_a_key_is_skipped(cog: UniMod) -> None:
    response = FakeErrorResponse(status=504, body="")
    tokens = {"openai": {"api_key": "nim-key"}, "gemini": {}}
    cog.bot.get_shared_api_tokens = AsyncMock(side_effect=lambda service: tokens[service])  # type: ignore[method-assign]

    with patch("unimod.unimod.aiohttp.ClientSession", return_value=FakeSession(response)):
        with pytest.raises(RuntimeError) as exc_info:
            await cog._analyze_with_ai("system prompt", "user prompt")

    assert "gemini" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_no_keys_at_all_says_how_to_set_one(cog: UniMod) -> None:
    cog.bot.get_shared_api_tokens = AsyncMock(return_value={})  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="set api openai"):
        await cog._analyze_with_ai("system prompt", "user prompt")


def test_safe_exception_text_falls_back_when_str_raises(cog: UniMod) -> None:
    """Broken exception stringification should still produce readable fallback text."""

    class BrokenStrError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("broken __str__")

    error_text = cog._safe_exception_text(BrokenStrError("boom"))

    assert "BrokenStrError" in error_text
    assert "str() failed" in error_text


@pytest.mark.asyncio
async def test_gemini_is_asked_to_think_hard(cog: UniMod) -> None:
    session = FallbackSession()
    session.models.append("pretend the first call already failed")
    payloads: list[dict[str, Any]] = []
    post = session.post
    session.post = lambda *a, **kw: payloads.append(kw["json"]) or post(*a, **kw)  # type: ignore[method-assign]
    tokens = {"openai": {}, "gemini": {"api_key": "gemini-key"}}
    cog.bot.get_shared_api_tokens = AsyncMock(side_effect=lambda service: tokens[service])  # type: ignore[method-assign]

    with patch("unimod.unimod.aiohttp.ClientSession", return_value=session):
        await cog._analyze_with_ai("system prompt", "user prompt")

    assert payloads[0]["model"] == "gemini-3.8-flash"
    assert payloads[0]["reasoning_effort"] == "high"
    assert payloads[0]["temperature"] == 1.0


@pytest.mark.asyncio
async def test_a_stream_error_fails_the_model(cog: UniMod) -> None:
    response = SimpleNamespace(content=sse({"error": {"message": "overloaded"}}))

    with pytest.raises(ValueError, match="overloaded"):
        await cog._read_stream(response)  # type: ignore[arg-type]
