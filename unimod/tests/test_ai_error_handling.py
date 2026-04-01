"""Regression tests for UniMod AI error handling."""

from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
import pytest

from unimod.unimod import UniMod


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
async def test_analyze_with_ai_non_200_preserves_original_http_error(cog: UniMod) -> None:
    """Non-200 responses should preserve the original API failure details."""
    error_text = "upstream bad request"
    response = FakeErrorResponse(status=500, body=error_text)

    with patch("unimod.unimod.aiohttp.ClientSession", return_value=FakeSession(response)):
        with pytest.raises(aiohttp.ClientResponseError) as exc_info:
            await cog._analyze_with_ai("system prompt", "user prompt")

    assert cog._last_ai_error == f"API Error 500: {error_text}"

    exc_text = str(exc_info.value)
    assert "NanoGPT API Error 500: upstream bad request" in exc_text
    assert "integrate.api.nvidia.com/v1/chat/completions" in exc_text


def test_safe_exception_text_falls_back_when_str_raises(cog: UniMod) -> None:
    """Broken exception stringification should still produce readable fallback text."""

    class BrokenStrError(Exception):
        def __str__(self) -> str:
            raise RuntimeError("broken __str__")

    error_text = cog._safe_exception_text(BrokenStrError("boom"))

    assert "BrokenStrError" in error_text
    assert "str() failed" in error_text
