"""
Configuration for LoRAs available in the generator.
"""

# Dictionary key is the style name used in the command
LORAS = {
    "Gothic": {
        "name": "Gothic Style Pony",
        "description": "Niji Midjourney aesthetic of goth style from MoriiMee",
        "model_id": "civitai:1122823",  # Placeholder
        "trigger_words": ["morimee_style", "cute face"],
        "prompt": "nun,latex,bdsm outfit",
        "strength": 0.8,
        "base": "Pony",
        "image_url": "https://example.com/anime_preview.png"
    },
    "Fantasy Styles": {
        "name": "Mythic Fantasy Styles",
        "description": "Velvet's Mythic Fantasy Styles",
        "model_id": "civitai:704723",
        "trigger_words": ["mythp0rt"],
        "prompt": "MythP0rt",
        "strength": 0.6,
        "base": "Pony",
        "image_url": "https://image.civitai.com/xG1nkqKTMzGDvpLrqFT7WA/044f5c70-f0ad-4ff2-9b21-a69d485863d8/width=525/044f5c70-f0ad-4ff2-9b21-a69d485863d8.jpeg"
    },
    "Realistic Skin": {
        "name": "Realistic Skin Texture",
        "description": "Realistic Skin Texture style (Detailed Skin)",
        "model_id": "civitai:1790871",
        "trigger_words": ["sharp", "detailed"],
        "prompt": "cinematic style, cinematic photography style",
        "strength": 0.5,
        "base": "Pony",
        "image_url": ""
    },
    "Feet": {
        "name": "Feet ",
        "description": "Better Feet",
        "model_id": "civitai:1361136",
        "trigger_words": ["feet"],
        "prompt": "detailed feet, realistic feet",
        "strength": 0.5,
        "base": "Pony",
        "image_url": ""
    },
    "Hands": {
        "name": "Hands ",
        "description": "Better Hands",
        "model_id": "civitai:1356581",
        "trigger_words": ["hand"],
        "prompt": "detailed hand, realistic hand",
        "strength": 0.5,
        "base": "Pony",
        "image_url": ""
    },
    "Anime Artistic": {
        "name": "Anime Artistic",
        "description": "Artistic anime style from Art8st",
        "model_id": "civitai:1795350",
        "trigger_words": ["Art8st", "Anime"],
        "prompt": "Art8st",
        "strength": 0.6,
        "base": "Pony",
        "image_url": ""
    },
    "Colored Pencil": {
        "name": "Hyperdetailed Colored Pencil",
        "description": "Hyperdetailed Colored Pencil style",
        "model_id": "civitai:1753238",
        "trigger_words": ["ArsMJStyle"],
        "prompt": "ArsMJStyle, Colored pencil hyperdetailed realism",
        "strength": 0.6,
        "base": "Pony",
        "image_url": ""
    },
}
