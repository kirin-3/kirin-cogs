import aiohttp
import asyncio
import re
import time
import logging
from typing import Optional, List, Dict, Any
from ..constants import NSFW_TERMS, SFW_NEGATIVE_PROMPT

log = logging.getLogger("red.unicornimage.horde")

class HordeClient:
    def __init__(self, session: aiohttp.ClientSession, api_key: str = "0000000000"):
        self.session = session
        self.api_key = api_key
        self.base_url = "https://stablehorde.net/api/v2"
        self.headers = {
            "apikey": self.api_key,
            "Client-Agent": "UnicornImage:v1.0.0:Unknown",
            "Content-Type": "application/json"
        }

    async def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 832,
        height: int = 1216,
        steps: int = 30,
        guidance_scale: float = 5,
        seed: Optional[int] = None,
        model_id: str = "CyberRealistic Pony", 
        loras: Optional[List[Dict[str, Any]]] = None,
        batch_size: int = 1,
        sampler: Optional[str] = None,
        clip_skip: int = 2,
        nsfw: bool = False,
        api_key: Optional[str] = None
    ) -> List[bytes]:
        
        # Update headers if specific key provided for this call
        headers = self.headers.copy()
        if api_key:
            headers["apikey"] = api_key

        if not nsfw:
            # Enforce SFW
            pattern = re.compile(r'\b(' + '|'.join(map(re.escape, NSFW_TERMS)) + r')\b', re.IGNORECASE)
            prompt = pattern.sub("", prompt)
            
            if negative_prompt:
                 negative_prompt = f"{negative_prompt}, {SFW_NEGATIVE_PROMPT}"
            else:
                 negative_prompt = SFW_NEGATIVE_PROMPT
        
        params = {
            "n": batch_size,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": guidance_scale,
            "sampler_name": sampler or "k_dpmpp_2m",
            "karras": True,
            "clip_skip": clip_skip,
        }

        if seed is not None:
            params["seed"] = str(seed)

        if loras:
            params["loras"] = loras
        
        payload = {
            "prompt": f"{prompt} ### {negative_prompt}" if negative_prompt else prompt,
            "params": params,
            "nsfw": nsfw,
            "censor_nsfw": not nsfw,
            "models": [model_id],
            "r2": True,
        }
        
        async with self.session.post(f"{self.base_url}/generate/async", json=payload, headers=headers) as resp:
            if resp.status != 202:
                try:
                    error_text = await resp.json()
                except:
                    error_text = await resp.text()
                log.error(f"Horde API Error ({resp.status}): {error_text}")
                raise Exception(f"Horde API submission failed ({resp.status}): {error_text}")
            
            data = await resp.json()
            generation_id = data.get("id")
            if not generation_id:
                raise Exception("Horde API did not return a generation ID")

        # Polling
        start_time = time.time()
        timeout = 600 
        
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError("Horde generation timed out")
            
            await asyncio.sleep(2)
            
            async with self.session.get(f"{self.base_url}/generate/check/{generation_id}", headers=headers) as resp:
                if resp.status != 200:
                    continue
                
                status_data = await resp.json()
                
                if status_data.get("faulted"):
                    raise Exception("Horde generation faulted (worker error)")
                    
                if status_data.get("done"):
                    break
        
        # Retrieve Results
        async with self.session.get(f"{self.base_url}/generate/status/{generation_id}", headers=headers) as resp:
            if resp.status != 200:
                    raise Exception("Failed to retrieve Horde results")
            
            result_data = await resp.json()
        
        generations = result_data.get("generations", [])
        images_bytes = []
        
        for gen in generations:
            img_url = gen.get("img")
            if img_url:
                async with self.session.get(img_url) as img_resp:
                    if img_resp.status == 200:
                        content = await img_resp.read()
                        images_bytes.append(content)
                    else:
                        log.warning(f"Failed to download image from {img_url}")
        
        if not images_bytes:
            raise Exception("No images generated or downloaded successfully")
            
        return images_bytes
