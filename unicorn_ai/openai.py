import logging
import re
from typing import Any

import aiohttp

log = logging.getLogger("red.unicorn_ai.openai")

DEFAULT_ENDPOINT = "https://nano-gpt.com/api/v1/chat/completions"
DEFAULT_MODEL = "zai-org/glm-5:thinking"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=180)

# Reasoning models may inline their thinking; drop it, including an unclosed block cut off by max_tokens.
_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|$)", flags=re.DOTALL)


class AIRequestError(Exception):
    """The AI endpoint could not produce a reply. The message is safe to log, never to post as the persona."""


def clean_reply(text: str) -> str:
    """Strip reasoning blocks and surrounding whitespace from a model reply."""
    return _THINK_BLOCK.sub("", text).strip()


class OpenAIClient:
    def __init__(self, bot):
        self.bot = bot

    async def generate_response(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        system_instruction: str,
        history: list[dict[str, Any]],
        after_context: str | None = None,
    ) -> str | None:
        """
        Generates a response from an OpenAI-compatible endpoint.

        Returns the reply text, or None when the model replied with nothing.
        Raises AIRequestError when the request or the response is unusable.
        """
        messages = [{"role": "system", "content": system_instruction}]

        # History entries use role "user" / "model" with parts[].text
        for msg in history:
            content = msg["parts"][0]["text"] if msg["parts"] else ""
            if content:
                messages.append({"role": "assistant" if msg["role"] == "model" else "user", "content": content})

        # Append after_context as last user message
        if after_context:
            messages.append({"role": "user", "content": after_context})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.95,
            "top_p": 0.93,
            "top_k": 40,
            "max_tokens": 8192,
        }

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        try:
            async with (
                aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session,
                session.post(endpoint, json=payload, headers=headers) as resp,
            ):
                if resp.status != 200:
                    error_text = (await resp.text())[:500]
                    log.error(f"OpenAI API Error {resp.status}: {error_text}")
                    raise AIRequestError(f"HTTP {resp.status}: {error_text}")
                data = await resp.json(content_type=None)
        except AIRequestError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as e:
            log.error(f"Request to {endpoint} failed: {e!r}")
            raise AIRequestError(f"Request failed: {e!r}") from e

        try:
            choices = data.get("choices") or []
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content")
        except (AttributeError, TypeError) as e:
            log.error(f"Failed to parse response: {e}")
            raise AIRequestError(f"Unexpected response shape: {e}") from e

        if not isinstance(content, str):
            return None
        return clean_reply(content) or None
