"""
Configuration for Base Models available in the generator.
"""

# Dictionary key is the model alias used in the command
MODELS = {
    "standard": {
        "name": "AutismMix SDXL",
        "description": "General purpose SDXL model",
        "id": "civitai:2469412", 
        "base": "SDXL"
    },
    "pony": {
        "name": "Pony Diffusion V6",
        "description": "High quality stylized model",
        "id": "civitai:257749",
        "base": "Pony"
    }
}

DEFAULT_MODEL = "standard"
