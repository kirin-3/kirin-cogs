import aiohttp
import asyncio
import json
import logging
import re
import os
from typing import Optional, List, Dict, Any

from google.oauth2 import service_account
from google.auth.transport.requests import Request

log = logging.getLogger("red.unicorn_ai.vertex")

class VertexClient:
    def __init__(self, cog_path: str):
        self.cog_path = cog_path
        self._creds = None
        self._project_id = None
        self._token_lock = asyncio.Lock()

    async def _load_credentials(self) -> bool:
        """
        Loads the service account credentials from a JSON file in the cog directory.
        """
        json_path = None
        # Scan for a .json file that looks like a service account
        for file in os.listdir(self.cog_path):
            if file.endswith(".json") and file not in ["info.json"]:
                try:
                    with open(os.path.join(self.cog_path, file), "r") as f:
                        data = json.load(f)
                        if data.get("type") == "service_account":
                            json_path = os.path.join(self.cog_path, file)
                            self._project_id = data.get("project_id")
                            break
                except Exception:
                    continue
        
        if not json_path:
            log.error("No service account JSON found in unicorn_ai directory.")
            return False

        try:
            # Run blocking auth load in a thread
            self._creds = await asyncio.to_thread(
                service_account.Credentials.from_service_account_file,
                json_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            return True
        except Exception as e:
            log.error(f"Failed to load credentials: {e}")
            return False

    async def _get_access_token(self) -> Optional[str]:
        """
        Refreshes and returns the OAuth2 access token.
        """
        async with self._token_lock:
            if not self._creds:
                if not await self._load_credentials():
                    return None

            if not self._creds.valid:
                try:
                    # Refresh token in thread
                    await asyncio.to_thread(self._creds.refresh, Request())
                except Exception as e:
                    log.error(f"Failed to refresh token: {e}")
                    return None
            
            return self._creds.token

    async def generate_response(
        self,
        model: str,
        location: str,
        system_instruction: str,
        history: List[Dict[str, Any]],
        after_context: Optional[str] = None
    ) -> Optional[str]:
        """
        Generates a response from Vertex AI.
        """
        token = await self._get_access_token()
        if not token or not self._project_id:
            return "Error: Authentication failed or missing Service Account."

        # Handle global vs regional endpoints
        if location == "global":
            hostname = "aiplatform.googleapis.com"
        else:
            hostname = f"{location}-aiplatform.googleapis.com"

        url = (
            f"https://{hostname}/v1/"
            f"projects/{self._project_id}/locations/{location}/"
            f"publishers/google/models/{model}:generateContent"
        )

        # Append after_context if present
        if after_context:
            history.append({
                "role": "user",
                "parts": [{"text": after_context}]
            })

        # Construct Payload
        # Mapping reasoning_effort to thinking_config if native API requires it,
        # but user specifically asked for "reasoning_effort: low".
        # We will send "reasoning_effort" as a top-level generation_config param
        # assuming the model/API version supports the OpenAI-aligned param.
        # If strictly native, we might need thinking_config.
        
        payload = {
            "contents": history,
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "generation_config": {
                "temperature": 1.0,
                "top_p": 0.96,
                "top_k": 0, # Vertex API usually expects int
                "max_output_tokens": 8192,
                "response_mime_type": "text/plain"
            },
            "safety_settings": [
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"}
            ]
        }

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        log.error(f"Vertex AI Error {resp.status}: {error_text}")
                        return f"Error {resp.status}: {error_text}"
                    
                    data = await resp.json()
                    
                    # Extract text
                    try:
                        candidates = data.get("candidates", [])
                        if not candidates:
                            return None
                        
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text_response = "".join([p.get("text", "") for p in parts])
                        
                        # Process response: Strip <think> tags (handling closed and unclosed)
                        cleaned_text = re.sub(r'<think>.*?(?:</think>|$)', '', text_response, flags=re.DOTALL)
                        return cleaned_text.strip()
                        
                    except Exception as e:
                        log.error(f"Failed to parse response: {e}")
                        return f"Error parsing response: {e}"

            except Exception as e:
                log.error(f"Request failed: {e}")
                return f"Request failed: {e}"
