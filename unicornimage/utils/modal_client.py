import modal
import logging
import re
from typing import Optional, List, Dict, Any
from ..constants import NSFW_TERMS, SFW_NEGATIVE_PROMPT

log = logging.getLogger("red.unicornimage.modal")

class ModalClient:
    def __init__(self, app_name: str = "text2image"):
        self.app_name = app_name
        self.inference_cls = None
        self.reload_app()

    def reload_app(self, app_name: Optional[str] = None):
        if app_name:
            self.app_name = app_name
        try:
            self.inference_cls = modal.Cls.from_name(self.app_name, "Inference")
            log.info(f"Successfully loaded Modal app: {self.app_name}")
        except Exception as e:
            log.error(f"Failed to lookup Modal function '{self.app_name}': {e}")
            self.inference_cls = None

    async def generate(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 30,
        guidance_scale: float = 7.5,
        seed: Optional[int] = None,
        model_id: Optional[str] = None,
        loras: Optional[List[Dict[str, Any]]] = None,
        batch_size: int = 1,
        scheduler: Optional[str] = None,
        clip_skip: Optional[int] = None,
        nsfw: bool = False,
    ) -> List[bytes]:
        
        # SFW filtering removed for Modal as per configuration.
        # User is responsible for content or model handles it.

        if not self.inference_cls:
            self.reload_app()
            if not self.inference_cls:
                raise RuntimeError("Modal client not initialized. Is 'modal' installed and authenticated?")

        inference_obj = self.inference_cls()
        
        try:
            log.info(f"Sending request to Modal - Prompt: '{prompt}'")
            
            # Note: The remote run method does not accept 'nsfw' argument
            images = await inference_obj.run.remote.aio(
                prompt=prompt,
                batch_size=batch_size,
                negative_prompt=negative_prompt,
                seed=seed,
                model_id=model_id,
                width=width,
                height=height,
                num_inference_steps=steps,
                guidance_scale=guidance_scale,
                loras=loras,
                clip_skip=clip_skip,
                scheduler=scheduler,
            )
            return images
        except Exception as e:
            log.error(f"Error calling Modal function: {e}")
            raise e
