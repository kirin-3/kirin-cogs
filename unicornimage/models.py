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
    "CyberRealistic Pony": {
        "name": "CyberRealistic Pony",
        "description": "CyberRealistic Pony blends all the charm of Pony Diffusion with the striking realism of CyberRealistic. The vibe? You get everything from adorable to bold (sometimes both at once) with crazy-detailed textures, moody cinematic lighting, and a hint of AI flair.",
        "id": "civitai:2469412",
        "base": "Pony"
    }
}

DEFAULT_MODEL = "standard"
