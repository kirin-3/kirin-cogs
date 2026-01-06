"""
Configuration for Base Models available in the generator.
"""

# Dictionary key is the model alias used in the command
MODELS = {
    "Hassaku XL": {
        "name": "Hassaku XL",
        "description": "Hassaku aims to be a anime model with a bright and distinct anime style.",
        "id": "civitai:378499", 
        "base": "SDXL",
        "width": 832,
        "height": 1216,
        "steps": 30,
        "cfg": 6.0,
        "clip_skip": 1,
        "sampler": "euler_ancestral"
    },
    "Nova Anime XL Pony": {
        "name": "Nova Anime XL Pony",
        "description": "Nova Anime XL is Nova Anime: Anime/2.5D/3D checkpoint model",
        "id": "civitai:994669",
        "base": "Pony",
        "width": 832,
        "height": 1216,
        "steps": 30,
        "cfg": 6.5,
        "clip_skip": 2,
        "sampler": "euler_ancestral"
    },
    "CyberRealistic Pony": {
        "name": "CyberRealistic Pony",
        "description": "CyberRealistic Pony blends all the charm of Pony Diffusion with the striking realism of CyberRealistic.",
        "id": "civitai:2469412", 
        "base": "Pony",
        "width": 896,
        "height": 1152,
        "steps": 28,
        "cfg": 5.0,
        "clip_skip": 2,
        "sampler": "dpmpp_2m_karras"
    }
}

DEFAULT_MODEL = "CyberRealistic Pony"
