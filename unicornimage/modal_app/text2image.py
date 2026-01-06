import io
import os
import json
import random
import time
import requests
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Literal, TYPE_CHECKING

import modal

# Import prompt chunking utility
try:
    from .prompt_utils import encode_prompt_chunked, MAX_TOKEN_LENGTH
except ImportError:
    # Fallback for local execution or if import fails
    from prompt_utils import encode_prompt_chunked, MAX_TOKEN_LENGTH

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("text2image")

if TYPE_CHECKING:
    import torch

MINUTES = 60

app = modal.App("text2image")

CACHE_DIR = "/cache"
CIVITAI_MODELS_DIR = "/cache/civitai"
CIVITAI_LORAS_DIR = "/cache/civitai/loras"
HF_LORAS_DIR = "/cache/hf/loras"

SchedulerType = Literal[
    "euler_ancestral",
    "dpmpp_2m_karras"
]

GPU_TYPE = os.environ.get("GPU_TYPE", "L4")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "accelerate==0.33.0",
        "diffusers==0.31.0",
        "fastapi[standard]==0.115.4",
        "huggingface-hub[hf_transfer]==0.25.2",
        "sentencepiece==0.2.0",
        "torch==2.5.1",
        "torchvision==0.20.1",
        "transformers~=4.44.0",
        "requests>=2.28.0",
        "safetensors>=0.4.1",
        "peft>=0.8.2",  
        "safetensors", 
        "xformers>=0.0.21", 
    )
    .env(
        {
            "HF_HUB_ENABLE_HF_TRANSFER": "1",  
            "HF_HUB_CACHE": CACHE_DIR,
        }
    )
)

civitai_secret = modal.Secret.from_name("civitai-token")

with image.imports():
    import diffusers
    import torch
    from fastapi import Response
    from huggingface_hub import hf_hub_download
    from diffusers.models.attention_processor import AttnProcessor2_0
    from diffusers.schedulers import (
        EulerAncestralDiscreteScheduler,
        DPMSolverMultistepScheduler,
    )
    from diffusers import AutoencoderKL
    import peft
    from transformers import CLIPTextModel, CLIPTextModelWithProjection, CLIPTokenizer, CLIPTextConfig
    import safetensors.torch
    
    def get_gpu_memory_info():
        if torch.cuda.is_available():
            t = torch.cuda.get_device_properties(0).total_memory
            r = torch.cuda.memory_reserved(0)
            a = torch.cuda.memory_allocated(0)
            f = t - (r + a)  
            return {
                "total": t / (1024**2),  
                "reserved": r / (1024**2),
                "allocated": a / (1024**2),
                "free": f / (1024**2)
            }
        return {"error": "CUDA not available"}


DEFAULT_MODEL_ID = "civitai:2469412"
DEFAULT_REFINER_MODEL_ID = "stabilityai/stable-diffusion-xl-refiner-1.0"

DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
DEFAULT_STEPS = 30  
DEFAULT_GUIDANCE_SCALE = 7.5
DEFAULT_SCHEDULER = "euler_ancestral"  

cache_volume = modal.Volume.from_name("hf-hub-cache", create_if_missing=True)


def parse_loras(loras_json: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    if not loras_json:
        return None
    try:
        lora_list = json.loads(loras_json)
        if not isinstance(lora_list, list):
            lora_list = [lora_list]
        return lora_list
    except Exception as e:
        logger.error(f"Error parsing LoRAs: {str(e)}")
        return None


@app.cls(
    image=image,
    gpu=GPU_TYPE,
    cpu=2.0,  
    memory=16384,  
    timeout=10 * MINUTES,
    scaledown_window=30,  
    volumes={CACHE_DIR: cache_volume},
    secrets=[civitai_secret],
)
class Inference:
    load_default_model: bool = modal.parameter(default=False)
    
    model_last_accessed = {}
    max_loaded_models = 2  
    loaded_loras = set()  

    AVAILABLE_SCHEDULERS = {
        "euler_ancestral": "Euler Ancestral",
        "dpmpp_2m_karras": "DPM++ 2M Karras"
    }

    @modal.enter()
    def setup(self):
        self.loaded_models = {}
        self.loaded_loras = set()  
        
        os.makedirs(CIVITAI_MODELS_DIR, exist_ok=True)
        os.makedirs(CIVITAI_LORAS_DIR, exist_ok=True)
        os.makedirs(HF_LORAS_DIR, exist_ok=True)
        
        logger.info(f"Initial GPU memory state: {get_gpu_memory_info()}")
        
        if self.load_default_model:
            logger.info("Pre-loading default SDXL model...")
            try:
                self._load_pipeline(DEFAULT_MODEL_ID)
                logger.info("Default SDXL model loaded successfully")
                logger.info(f"GPU memory after loading default model: {get_gpu_memory_info()}")
            except Exception as e:
                logger.warning(f"Failed to pre-load default model: {str(e)}")

    def _download_civitai_model(self, model_id):
        if not model_id.startswith("civitai:"):
            raise ValueError("CivitAI model IDs must start with 'civitai:'")

        civitai_id = model_id.split("civitai:")[1]

        model_dir = Path(f"{CIVITAI_MODELS_DIR}/{civitai_id}")
        model_dir.mkdir(exist_ok=True, parents=True)

        safetensor_files = list(model_dir.glob("*.safetensors"))
        if safetensor_files:
            logger.info(f"CivitAI model {civitai_id} already downloaded")
            return str(model_dir), safetensor_files[0].name

        token = os.environ.get("CIVITAI_TOKEN")
        download_url = f"https://civitai.com/api/download/models/{civitai_id}?token={token}"
        
        logger.info(f"Downloading CivitAI model from {download_url}")
        
        response = requests.get(download_url, stream=True)
        response.raise_for_status()
        
        if "Content-Disposition" in response.headers:
            content_disposition = response.headers["Content-Disposition"]
            filename = content_disposition.split("filename=")[1].strip('"')
        else:
            filename = f"model_{civitai_id}.safetensors"
            
        output_path = model_dir / filename
        
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        logger.info(f"Downloaded CivitAI model to {output_path}")
        return str(model_dir), filename
        
    def _download_civitai_lora(self, lora_id):
        civitai_id = lora_id.split("civitai:")[1]
        
        lora_dir = Path(f"{CIVITAI_LORAS_DIR}/{civitai_id}")
        lora_dir.mkdir(exist_ok=True, parents=True)
        
        safetensor_files = list(lora_dir.glob("*.safetensors"))
        if safetensor_files:
            logger.info(f"CivitAI LoRA {civitai_id} already downloaded")
            return str(safetensor_files[0])
            
        token = os.environ.get("CIVITAI_TOKEN")
        download_url = f"https://civitai.com/api/download/models/{civitai_id}?token={token}"
        
        logger.info(f"Downloading CivitAI LoRA from {download_url}")
        
        response = requests.get(download_url, stream=True)
        response.raise_for_status()
        
        if "Content-Disposition" in response.headers:
            content_disposition = response.headers["Content-Disposition"]
            filename = content_disposition.split("filename=")[1].strip('"')
        else:
            filename = f"lora_{civitai_id}.safetensors"
            
        output_path = lora_dir / filename
        
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        logger.info(f"Downloaded CivitAI LoRA to {output_path}")
        return str(output_path)

    def _download_hf_lora(self, lora_id):
        parts = lora_id.split("hf:")
        if len(parts) != 2:
            raise ValueError("Hugging Face LoRA IDs must be in format 'hf:repo_id/path'")
            
        repo_id_path = parts[1]
        
        if "/" in repo_id_path and not repo_id_path.endswith("/"):
            repo_id = repo_id_path.split("/")[0]
            file_path = "/".join(repo_id_path.split("/")[1:])
            
            lora_dir = Path(f"{HF_LORAS_DIR}/{repo_id}")
            lora_dir.mkdir(exist_ok=True, parents=True)
            
            target_file = lora_dir / file_path.split("/")[-1]
            if target_file.exists():
                logger.info(f"HF LoRA {repo_id_path} already downloaded")
                return str(target_file)
                
            logger.info(f"Downloading Hugging Face LoRA from {repo_id_path}")
            file_path = hf_hub_download(repo_id=repo_id, filename=file_path, cache_dir=CACHE_DIR)
            return file_path
        else:
            repo_id = repo_id_path.strip("/")
            try:
                logger.info(f"Searching for a LoRA file in {repo_id}")
                for filename in ["lora.safetensors", "pytorch_lora_weights.safetensors", "pytorch_lora_weights.bin"]:
                    try:
                        file_path = hf_hub_download(repo_id=repo_id, filename=filename, cache_dir=CACHE_DIR)
                        logger.info(f"Downloaded {filename} from {repo_id}")
                        return file_path
                    except:
                        pass
                        
                from huggingface_hub import list_repo_files
                files = list_repo_files(repo_id)
                
                for file in files:
                    if file.endswith(".safetensors") and ("lora" in file.lower() or "weight" in file.lower()):
                        file_path = hf_hub_download(repo_id=repo_id, filename=file, cache_dir=CACHE_DIR)
                        logger.info(f"Found and downloaded {file} from {repo_id}")
                        return file_path
                        
                raise ValueError(f"Could not find a LoRA file in {repo_id}")
            except Exception as e:
                raise ValueError(f"Error downloading LoRA from Hugging Face: {str(e)}")

    def _download_lora(self, lora_spec):
        model_id = lora_spec.get("model_id", "")
        
        if not model_id:
            raise ValueError("LoRA model_id is required")
            
        if model_id.startswith("civitai:"):
            return self._download_civitai_lora(model_id)
        elif model_id.startswith("hf:"):
            return self._download_hf_lora(model_id)
        else:
            raise ValueError(f"Unsupported LoRA source: {model_id}. Must start with 'civitai:' or 'hf:'")

    def _manage_model_memory(self, model_key):
        self.model_last_accessed[model_key] = time.time()
        
        if len(self.loaded_models) > self.max_loaded_models:
            logger.info(f"Cache limit reached ({len(self.loaded_models)} models). Unloading least recently used model.")
            logger.info(f"GPU memory before unloading: {get_gpu_memory_info()}")
            
            lru_model_key = min(self.model_last_accessed.items(), key=lambda x: x[1])[0]
            
            if lru_model_key != model_key and lru_model_key in self.loaded_models:
                logger.info(f"Unloading model {lru_model_key} from memory")
                
                try:
                    self._clean_peft_adapters(self.loaded_models[lru_model_key])
                    self.loaded_models[lru_model_key].to("cpu")
                    del self.loaded_models[lru_model_key]
                    del self.model_last_accessed[lru_model_key]
                    
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                        torch.cuda.synchronize()  
                        logger.info(f"Cleared CUDA cache, freeing GPU memory")
                        logger.info(f"GPU memory after unloading: {get_gpu_memory_info()}")
                except Exception as e:
                    logger.error(f"Error during model unloading: {e}")

    def _load_pipeline(self, model_id, loras=None):
        lora_key = ""
        if loras:
            sorted_loras = sorted(loras, key=lambda x: x.get('model_id', ''))
            lora_ids = [f"{lora['model_id']}:{lora['weight']}" for lora in sorted_loras]
            lora_key = "_loras_" + "_".join(lora_ids)
            
        model_key = f"{model_id}{lora_key}"
        
        logger.info(f"Looking for model with key: {model_key}")
        logger.info(f"Current loaded models: {list(self.loaded_models.keys())}")
        logger.info(f"Current GPU memory: {get_gpu_memory_info()}")
        
        if model_key not in self.loaded_models:
            logger.info(f"Model not found in cache. Loading SDXL model: {model_id}")
            try:
                base_model_key = None
                for key in self.loaded_models.keys():
                    if key.startswith(model_id) and loras:  
                        base_model_key = key
                        logger.info(f"Found base model already loaded: {base_model_key}")
                        break
                    
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
                    
                target_dtype = torch.float16
                logger.info(f"Using torch_dtype: {target_dtype}")
                
                if base_model_key and base_model_key in self.loaded_models:
                    logger.info(f"Reusing base model {model_id} and applying new LoRAs")
                    pipeline = self.loaded_models[base_model_key]
                    self._clean_peft_adapters(pipeline)
                    del self.loaded_models[base_model_key]
                    if base_model_key in self.model_last_accessed:
                        del self.model_last_accessed[base_model_key]
                else:    
                    if model_id.startswith("civitai:"):
                        model_path, model_filename = self._download_civitai_model(model_id)
                        
                        logger.info(f"Loading CivitAI SDXL model from {model_path}/{model_filename}")
                        pipeline = diffusers.StableDiffusionXLPipeline.from_single_file(
                            f"{model_path}/{model_filename}",
                            torch_dtype=target_dtype,
                            use_safetensors=True,
                        )
                    else:
                        pipeline = diffusers.StableDiffusionXLPipeline.from_pretrained(
                            model_id,
                            torch_dtype=target_dtype,
                            use_safetensors=True,
                            variant="fp16" if target_dtype == torch.float16 else "bf16",
                        )
                
                if model_id.startswith("civitai:") or model_id != DEFAULT_MODEL_ID:
                    try:
                        logger.info("Attempting to load and set 'madebyollin/sdxl-vae-fp16-fix' VAE")
                        vae = AutoencoderKL.from_pretrained(
                            "madebyollin/sdxl-vae-fp16-fix",
                            torch_dtype=target_dtype
                        )
                        pipeline.vae = vae.to("cuda")
                        logger.info("Successfully loaded and set 'madebyollin/sdxl-vae-fp16-fix' VAE.")
                    except Exception as e:
                        logger.warning(f"Could not load 'madebyollin/sdxl-vae-fp16-fix': {e}. Using model's default VAE.")
                
                pipeline = pipeline.to("cuda")
                
                try:
                    if hasattr(pipeline, "enable_xformers_memory_efficient_attention"):
                        pipeline.enable_xformers_memory_efficient_attention()
                        logger.info("Enabled xformers memory efficient attention")
                    elif hasattr(pipeline, "enable_attention_slicing"):
                        pipeline.enable_attention_slicing()
                        logger.info("Enabled attention slicing as fallback")
                except Exception as e:
                    logger.warning(f"Could not enable optimized attention: {str(e)}")
                    logger.info("Using default attention mechanism")
                    try:
                        pipeline.enable_attention_slicing()
                        logger.info("Enabled attention slicing")
                    except:
                        pass
                
                if loras:
                    self._clean_peft_adapters(pipeline)
                    
                    loaded_adapter_names = []
                    adapter_weights = []
                    
                    successful_loras = []
                    failed_loras = []
                    
                    for lora_index, lora_spec in enumerate(loras):
                        weight = float(lora_spec.get("weight", 0.75))
                        lora_model_id = lora_spec.get("model_id", "")
                        
                        if not lora_model_id:
                            failed_loras.append(f"LoRA #{lora_index+1}: Missing model_id")
                            continue
                        
                        try:
                            lora_path = self._download_lora(lora_spec)
                            self.loaded_loras.add(lora_model_id)
                        except Exception as e:
                            failed_loras.append(f"LoRA {lora_model_id}: Download failed - {str(e)}")
                            continue
                        
                        logger.info(f"Applying LoRA {lora_index+1}/{len(loras)} from {lora_path} with weight {weight}")
                        try:
                            adapter_name = f"lora_{lora_index}"
                            pipeline.load_lora_weights(
                                lora_path, 
                                adapter_name=adapter_name
                            )
                            
                            loaded_adapter_names.append(adapter_name)
                            adapter_weights.append(weight)
                            
                            successful_loras.append(lora_model_id)
                            
                        except Exception as e:
                            logger.error(f"Error applying LoRA {lora_model_id}: {str(e)}")
                            failed_loras.append(f"LoRA {lora_model_id}: Application failed - {str(e)}")
                    
                    if loaded_adapter_names:
                        try:
                            logger.info(f"Setting adapters: {loaded_adapter_names} with weights: {adapter_weights}")
                            pipeline.set_adapters(loaded_adapter_names, adapter_weights)
                            logger.info(f"Successfully applied {len(successful_loras)} LoRAs with adapter fusion.")
                        except Exception as e_set_adapters:
                            logger.error(f"Error during pipeline.set_adapters: {e_set_adapters}")
                            failed_loras.extend([f"{lid} (set_adapters failed)" for lid in successful_loras])
                            successful_loras = [] 
                    
                    if successful_loras:
                        logger.info(f"Successfully loaded {len(successful_loras)}/{len(loras)} LoRAs: {', '.join(successful_loras)}")
                    if failed_loras:
                        logger.warning(f"Failed to load {len(failed_loras)}/{len(loras)} LoRAs:")
                        for fail in failed_loras:
                            logger.warning(f"  - {fail}")
                
                self.loaded_models[model_key] = pipeline
                self._manage_model_memory(model_key)
                logger.info(f"GPU memory after loading model: {get_gpu_memory_info()}")
            except Exception as e:
                logger.error(f"Failed to load SDXL model: {str(e)}")
                raise ValueError(f"Could not load SDXL model {model_id}: {str(e)}")
                
        else:
            logger.info(f"Model {model_key} already loaded, reusing from cache")
            self._manage_model_memory(model_key)
                
        return self.loaded_models[model_key]
        
    def _clean_peft_adapters(self, pipeline):
        logger.info("Starting deep PEFT adapter cleanup")
        try:
            if hasattr(pipeline, "unload_lora_weights"):
                pipeline.unload_lora_weights()
                logger.info("Called unload_lora_weights")
                
            if hasattr(pipeline, "unet"):
                for name, module in pipeline.unet.named_modules():
                    if hasattr(module, "peft_config"):
                        delattr(module, "peft_config")
                        
            if hasattr(pipeline, "unet") and hasattr(pipeline.unet, "disable_adapter"):
                logger.info("Disabling UNet adapter")
                pipeline.unet.disable_adapter()
                
            if hasattr(pipeline, "unet"):
                from diffusers.models.lora import LoRACompatibleLinear
                from peft.tuners.lora import LoraLayer
                
                for module in pipeline.unet.modules():
                    if isinstance(module, LoRACompatibleLinear) and hasattr(module, "lora_layer"):
                        module.lora_layer = None
                    elif hasattr(module, "_lora_layer"):
                        module._lora_layer = None
                    elif isinstance(module, LoraLayer):
                        if hasattr(module, "lora_A"):
                            module.lora_A.data.zero_()
                        if hasattr(module, "lora_B"):
                            module.lora_B.data.zero_()
                
            for encoder in [pipeline.text_encoder, pipeline.text_encoder_2]:
                if encoder is not None:
                    for module in encoder.modules():
                        if isinstance(module, LoRACompatibleLinear) and hasattr(module, "lora_layer"):
                            module.lora_layer = None
                        elif hasattr(module, "_lora_layer"):
                            module._lora_layer = None
                        elif isinstance(module, LoraLayer):
                            if hasattr(module, "lora_A"):
                                module.lora_A.data.zero_()
                            if hasattr(module, "lora_B"):
                                module.lora_B.data.zero_()
                
            if hasattr(pipeline, "active_adapters"):
                pipeline.active_adapters = None
                logger.info("Reset active_adapters")
                
            logger.info("Completed PEFT adapter cleanup")
            
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                
        except Exception as e:
            logger.warning(f"Warning during adapter cleanup: {e}")
            
    @modal.method()
    def run(
        self, 
        prompt: str, 
        batch_size: int = 1,
        negative_prompt: str = "",
        seed: Optional[int] = None,
        model_id: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        num_inference_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        loras: Optional[List[Dict[str, Any]]] = None,
        clip_skip: Optional[int] = None,
        scheduler: Optional[SchedulerType] = None,
    ) -> list[bytes]:
        logger.info(f"GPU memory before run: {get_gpu_memory_info()}")
        
        actual_model_id = model_id if model_id else DEFAULT_MODEL_ID
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            
        pipe = self._load_pipeline(actual_model_id, loras)
        
        if not hasattr(pipe, "_original_text_encoder_config_dict"):
            pipe._original_text_encoder_config_dict = pipe.text_encoder.config.to_dict()
        if hasattr(pipe, "text_encoder_2") and not hasattr(pipe, "_original_text_encoder_2_config_dict"):
            pipe._original_text_encoder_2_config_dict = pipe.text_encoder_2.config.to_dict()

        current_text_encoder_config = CLIPTextConfig.from_dict(pipe._original_text_encoder_config_dict.copy())
        pipe.text_encoder.config = current_text_encoder_config
        
        if hasattr(pipe, "text_encoder_2"):
            current_text_encoder_2_config = CLIPTextConfig.from_dict(pipe._original_text_encoder_2_config_dict.copy())
            pipe.text_encoder_2.config = current_text_encoder_2_config
        
        if clip_skip and clip_skip > 1:
            num_layers_to_actually_skip = clip_skip - 1

            if hasattr(pipe, "text_encoder") and num_layers_to_actually_skip > 0:
                original_layers1 = pipe.text_encoder.config.num_hidden_layers
                if num_layers_to_actually_skip < original_layers1:
                    logger.info(f"Applying CLIP skip {clip_skip} to text_encoder (original layers: {original_layers1}, using {original_layers1 - num_layers_to_actually_skip})")
                    pipe.text_encoder.config.num_hidden_layers = original_layers1 - num_layers_to_actually_skip
                else:
                    logger.warning(f"clip_skip={clip_skip} is too high for text_encoder with {original_layers1} layers. Not applying skip.")
            
            if hasattr(pipe, "text_encoder_2") and num_layers_to_actually_skip > 0:
                original_layers2 = pipe.text_encoder_2.config.num_hidden_layers
                if num_layers_to_actually_skip < original_layers2:
                    logger.info(f"Applying CLIP skip {clip_skip} to text_encoder_2 (original layers: {original_layers2}, using {original_layers2 - num_layers_to_actually_skip})")
                    pipe.text_encoder_2.config.num_hidden_layers = original_layers2 - num_layers_to_actually_skip
                else:
                    logger.warning(f"clip_skip={clip_skip} is too high for text_encoder_2 with {original_layers2} layers. Not applying skip.")
        
        seed = seed if seed is not None else random.randint(0, 2**32 - 1)
        logger.info(f"seeding RNG with {seed}")
        torch.manual_seed(seed)
        torch.cuda.manual_seed(seed)
        
        width = width if width is not None else DEFAULT_WIDTH
        height = height if height is not None else DEFAULT_HEIGHT
        
        width = max(512, min(2048, (width // 8) * 8))
        height = max(512, min(2048, (height // 8) * 8))
        
        steps = num_inference_steps if num_inference_steps is not None else DEFAULT_STEPS
        
        gs = guidance_scale if guidance_scale is not None else DEFAULT_GUIDANCE_SCALE
        
        if loras:
            lora_info = ", ".join([f"{lora.get('model_id')}:{lora.get('weight')}" for lora in loras])
            logger.info(f"Using LoRAs: {lora_info}")
            
        logger.info(f"Generating SDXL image with dimensions {width}x{height}, {steps} steps")
        
        generator = torch.Generator(device="cuda").manual_seed(seed)
        
        if scheduler:
            logger.info(f"Applying scheduler: {scheduler}")
            if scheduler == "euler_ancestral":
                pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(pipe.scheduler.config)
            elif scheduler == "dpmpp_2m_karras":
                pipe.scheduler = DPMSolverMultistepScheduler.from_config(
                    pipe.scheduler.config,
                    algorithm_type="dpmsolver++",
                    solver_order=2,
                    use_karras_sigmas=True
                )
            logger.info(f"Applied scheduler: {pipe.scheduler.__class__.__name__}")

        try:
            (
                prompt_embeds,
                negative_prompt_embeds,
                pooled_prompt_embeds,
                negative_pooled_prompt_embeds,
            ) = encode_prompt_chunked(
                pipe=pipe,
                prompt=prompt,
                negative_prompt=negative_prompt,
                device=pipe.device, 
                batch_size=1,  
                max_length=MAX_TOKEN_LENGTH
            )
            
            if batch_size > 1:
                prompt_embeds = prompt_embeds.repeat(batch_size, 1, 1)
                negative_prompt_embeds = negative_prompt_embeds.repeat(batch_size, 1, 1)
                pooled_prompt_embeds = pooled_prompt_embeds.repeat(batch_size, 1)
                negative_pooled_prompt_embeds = negative_pooled_prompt_embeds.repeat(batch_size, 1)
                logger.info(f"Expanded embeds for batch_size={batch_size}")

            logger.info(f"GPU memory before generation: {get_gpu_memory_info()}")
            
            images = pipe(
                prompt_embeds=prompt_embeds,
                negative_prompt_embeds=negative_prompt_embeds,
                pooled_prompt_embeds=pooled_prompt_embeds,
                negative_pooled_prompt_embeds=negative_pooled_prompt_embeds,
                num_images_per_prompt=1,  
                num_inference_steps=steps,
                guidance_scale=gs,
                width=width,
                height=height,
                generator=generator,
            ).images
            
            logger.info(f"GPU memory after generation: {get_gpu_memory_info()}")

            del prompt_embeds
            del negative_prompt_embeds
            del pooled_prompt_embeds
            del negative_pooled_prompt_embeds
            
            image_output = []
            for image in images:
                with io.BytesIO() as buf:
                    image.save(buf, format="PNG")
                    image_output.append(buf.getvalue())

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                
            logger.info(f"GPU memory after run and cleanup: {get_gpu_memory_info()}")
            
            return image_output
        
        except Exception as e:
            logger.error(f"Error during image generation: {e}")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            raise e
