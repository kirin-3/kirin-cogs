"""Tests for the OpenAI client integration in unicorn_ai."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from redbot.core.bot import Red

from unicorn_ai.openai import OpenAIClient


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

    async def json(self):
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
    post_mock.return_value = MockResponse(
        status=200, json_data={"choices": [{"message": {"content": "Hello human"}}]}
    )

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

    result = await client.generate_response(
        endpoint="", api_key="", model="", system_instruction="", history=[]
    )

    assert result == "Error 401: Invalid API Key"


@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_generate_response_missing_choices(post_mock: MagicMock, client: OpenAIClient) -> None:
    post_mock.return_value = MockResponse(status=200, json_data={})

    result = await client.generate_response(
        endpoint="", api_key="", model="", system_instruction="", history=[]
    )

    assert result is None
