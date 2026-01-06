"""
Configuration for LoRAs available in the generator.
"""

# Dictionary key is the style name used in the command
LORAS = {
    "anime": {
        "name": "Anime Style",
        "description": "High quality anime style generation",
        "model_id": "civitai:123456",  # Placeholder
        "trigger_words": ["anime style", "vivid colors"],
        "prompt": "anime screencap, studio ghibli style",
        "strength": 0.8,
        "image_url": "https://example.com/anime_preview.png"
    },
    "art-full": {
        "name": "art-full",
        "description": "art-full (CivitAI ID: 152309)",
        "model_id": "civitai:152309",
        "trigger_words": ["anime style", "vivid colors"],
        "prompt": "(best quality:1.1), sharp focus, studio photo, line art, simple white background, concept art,",
        "strength": 0.8,
        "image_url": ""
    },
    "FANTASY": {
        "name": "FANTASY",
        "description": "FANTASY (CivitAI ID: 984067)",
        "model_id": "civitai:984067",
        "trigger_words": ["fantasy style", "fantasy elements"],
        "prompt": "(best quality:1.1), fantasy themes, score_9, score_8_up, score_7_up, score_6_up, score_5_up,",
        "strength": 0.7,
        "image_url": ""
    }
}
