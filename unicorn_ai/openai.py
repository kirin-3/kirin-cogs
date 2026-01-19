import aiohttp
import logging
from typing import Optional, List, Dict, Any

log = logging.getLogger("red.unicorn_ai.openai")

class OpenAIClient:
    def __init__(self, bot):
        self.bot = bot
    
    async def generate_response(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        system_instruction: str,
        history: List[Dict[str, Any]],
        after_context: Optional[str] = None
    ) -> Optional[str]:
        """
        Generates a response from OpenAI-compatible endpoint.
        """
        # Convert Vertex format to OpenAI format
        messages = []
        
        # Add system instruction as first message
        messages.append({"role": "system", "content": system_instruction})
        
        # Convert history (Vertex format: role + parts[].text)
        for msg in history:
            role = msg["role"]  # "user" or "model"
            content = msg["parts"][0]["text"] if msg["parts"] else ""
            
            # Map Vertex "model" role to OpenAI "assistant"
            openai_role = "assistant" if role == "model" else "user"
            
            if content:
                messages.append({"role": openai_role, "content": content})
        
        # Append after_context as last user message
        if after_context:
            messages.append({"role": "user", "content": after_context})
        
        # Construct payload
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.95,
            "top_p": 0.93,
            "top_k": 40,
            "max_tokens": 8192
        }
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(endpoint, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        log.error(f"OpenAI API Error {resp.status}: {error_text}")
                        return f"Error {resp.status}: {error_text}"
                    
                    data = await resp.json()
                    
                    # Extract text from OpenAI format
                    try:
                        choices = data.get("choices", [])
                        if not choices:
                            return None
                        
                        content = choices[0].get("message", {}).get("content", "")
                        return content
                    except Exception as e:
                        log.error(f"Failed to parse response: {e}")
                        return f"Error parsing response: {e}"
            
            except Exception as e:
                log.error(f"Request failed: {e}")
                return f"Request failed: {e}"
