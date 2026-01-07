import json
import os
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

log = logging.getLogger("red.unicorn_ai.persona")

@dataclass
class Persona:
    name: str
    description: str
    system_prompt: str
    personality: str
    avatar_url: Optional[str] = None
    after_context: Optional[str] = None
    history_limit: Optional[int] = None
    first_message: Optional[str] = None
    examples: List[Dict[str, str]] = None
    allow_summon: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        # Validate history_limit
        history_limit = data.get("history_limit")
        if history_limit is not None:
            try:
                history_limit = int(history_limit)
            except (ValueError, TypeError):
                log.warning(f"Invalid history_limit for persona {data.get('name')}: {history_limit}. Ignoring.")
                history_limit = None

        return cls(
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            system_prompt=data.get("system_prompt", ""),
            personality=data.get("personality", ""),
            avatar_url=data.get("avatar_url"),
            after_context=data.get("after_context"),
            history_limit=history_limit,
            first_message=data.get("first_message"),
            examples=data.get("examples", []),
            allow_summon=data.get("allow_summon", False)
        )

class PersonaManager:
    def __init__(self, data_path: str):
        self.data_path = data_path
        self._summonable_cache: Optional[List[str]] = None

    def list_personas(self) -> List[str]:
        """Returns a list of available persona names (filenames without .json)."""
        if not os.path.exists(self.data_path):
            return []
        return [f[:-5] for f in os.listdir(self.data_path) if f.endswith(".json")]

    def load_persona(self, name: str) -> Optional[Persona]:
        """Loads a persona by name."""
        # Security check to prevent path traversal
        if ".." in name or "/" in name or "\\" in name:
            log.warning(f"Attempted path traversal in load_persona: {name}")
            return None

        filename = f"{name}.json"
        path = os.path.join(self.data_path, filename)
        
        if not os.path.exists(path):
            log.error(f"Persona file not found: {path}")
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Validation
                if "system_prompt" not in data:
                    log.warning(f"Persona {name} missing 'system_prompt'")
                return Persona.from_dict(data)
        except Exception as e:
            log.error(f"Failed to load persona {name}: {e}")
            return None

    def get_summonable_personas(self) -> List[str]:
        """Returns a cached list of personas that have allow_summon=True."""
        if self._summonable_cache is not None:
            return self._summonable_cache
            
        summonable = []
        all_names = self.list_personas()
        for name in all_names:
            p = self.load_persona(name)
            if p and p.allow_summon:
                summonable.append(name)
        
        self._summonable_cache = summonable
        return summonable
