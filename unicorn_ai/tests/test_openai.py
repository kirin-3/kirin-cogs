"""Tests for the OpenAI client integration in unicorn_ai."""

from typing import Any
from unittest.mock import MagicMock, patch

import aiohttp
import pytest
from redbot.core.bot import Red

from unicorn_ai.openai import AIRequestError, OpenAIClient, clean_reply


@pytest.fixture
def bot_mock() -> MagicMock:
    return MagicMock(spec=Red)


@pytest.fixture
def client(bot_mock: MagicMock) -> OpenAIClient:
    return OpenAIClient(bot_mock)


class MockResponse:
    def __init__(self, status: int, json_data: dict[str, Any] | None = None, text_data: str = ""):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def json(self, **kwargs):
        return self._json_data

    async def text(self):
        return self._text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_generate_response_payload_mapping(post_mock: MagicMock, client: OpenAIClient) -> None:
    # Setup mock return data
    post_mock.return_value = MockResponse(status=200, json_data={"choices": [{"message": {"content": "Hello human"}}]})

    history = [
        {"role": "user", "parts": [{"text": "Hi"}]},
        {"role": "model", "parts": [{"text": "Greetings"}]},
    ]

    result = await client.generate_response(
        endpoint="https://api.example.com/v1/chat",
        api_key="secret",
        model="gpt-4",
        system_instruction="You are a bot",
        history=history,
        after_context="Do something cool",
    )

    assert result == "Hello human"

    # Verify the request payload structure
    post_mock.assert_called_once()
    args, kwargs = post_mock.call_args
    assert args[0] == "https://api.example.com/v1/chat"

    payload = kwargs["json"]
    assert payload["model"] == "gpt-4"
    assert payload["temperature"] == 0.95

    messages = payload["messages"]
    assert len(messages) == 4
    assert messages[0] == {"role": "system", "content": "You are a bot"}
    assert messages[1] == {"role": "user", "content": "Hi"}
    assert messages[2] == {"role": "assistant", "content": "Greetings"}
    assert messages[3] == {"role": "user", "content": "Do something cool"}

    headers = kwargs["headers"]
    assert headers["Authorization"] == "Bearer secret"
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_generate_response_error_status(post_mock: MagicMock, client: OpenAIClient) -> None:
    post_mock.return_value = MockResponse(status=401, text_data="Invalid API Key")

    with pytest.raises(AIRequestError, match="401"):
        await client.generate_response(endpoint="", api_key="", model="", system_instruction="", history=[])


@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_generate_response_connection_error_raises(post_mock: MagicMock, client: OpenAIClient) -> None:
    post_mock.side_effect = aiohttp.ClientConnectionError("refused")

    with pytest.raises(AIRequestError, match="Request failed"):
        await client.generate_response(endpoint="", api_key="", model="", system_instruction="", history=[])


@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_generate_response_strips_thinking(post_mock: MagicMock, client: OpenAIClient) -> None:
    post_mock.return_value = MockResponse(
        status=200, json_data={"choices": [{"message": {"content": "<think>plan</think>\n Hello"}}]}
    )

    result = await client.generate_response(endpoint="", api_key="", model="", system_instruction="", history=[])

    assert result == "Hello"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [None, "", "<think>only thinking, cut off"])
@patch("aiohttp.ClientSession.post")
async def test_generate_response_empty_content_is_none(
    post_mock: MagicMock, client: OpenAIClient, content: object
) -> None:
    post_mock.return_value = MockResponse(status=200, json_data={"choices": [{"message": {"content": content}}]})

    result = await client.generate_response(endpoint="", api_key="", model="", system_instruction="", history=[])

    assert result is None


def test_clean_reply_handles_closed_and_unclosed_blocks() -> None:
    assert clean_reply("a<think>x</think>b") == "ab"
    assert clean_reply("reply<think>never closed") == "reply"


@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_generate_response_missing_choices(post_mock: MagicMock, client: OpenAIClient) -> None:
    post_mock.return_value = MockResponse(status=200, json_data={})

    result = await client.generate_response(endpoint="", api_key="", model="", system_instruction="", history=[])

    assert result is None
