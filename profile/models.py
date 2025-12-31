from typing import Dict, Optional, TypedDict

class ProfileData(TypedDict, total=False):
    name: str
    age: int
    location: str
    gender: str
    sexuality: str
    role: Optional[str]
    likes: Optional[str]
    dislikes: Optional[str]
    kinks: Optional[str]
    limits: Optional[str]
    about_me: Optional[str]
    picture_url: Optional[str]

# Constants for validation and UI
QUESTIONS = [
    {"id": "name", "label": "Name", "question": "What name do you go by?", "max_length": 50, "required": True},
    {"id": "age", "label": "Age", "question": "How old are you?", "max_length": 3, "required": True, "type": "int"},
    {"id": "location", "label": "Location", "question": "Where are you from? (Country or continent)", "max_length": 50, "required": True},
    {"id": "gender", "label": "Gender", "question": "What gender do you identify as?", "max_length": 100, "required": True},
    {"id": "sexuality", "label": "Sexuality", "question": "What is your sexuality?", "max_length": 100, "required": True},
    {"id": "role", "label": "Role", "question": "What role do you prefer? (Sub/Dom/Switch)", "max_length": 100, "required": False},
    {"id": "likes", "label": "Likes", "question": "What do you like in general? (Hobbies etc.)", "max_length": 1000, "required": False, "style": "long"},
    {"id": "dislikes", "label": "Dislikes", "question": "What do you dislike in general?", "max_length": 1000, "required": False, "style": "long"},
    {"id": "kinks", "label": "Kinks", "question": "What are your kinks?", "max_length": 1000, "required": False, "style": "long"},
    {"id": "limits", "label": "Limits", "question": "What are your limits?", "max_length": 1000, "required": False, "style": "long"},
    {"id": "about_me", "label": "About Me", "question": "Tell us a bit about yourself.", "max_length": 1000, "required": False, "style": "long"},
    {"id": "picture", "label": "Picture", "question": "Upload a picture of yourself.", "required": False, "type": "image"},
]

PROFILE_CHANNEL_ID = 686091267012296714
UNIQUE_ID = 0x6AFE8001
