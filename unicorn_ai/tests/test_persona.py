"""Tests for the PersonaManager class in unicorn_ai."""

import json
from pathlib import Path

import pytest

from unicorn_ai.persona import Persona, PersonaManager


def test_persona_from_dict_defaults() -> None:
    data = {"name": "Test Persona"}
    persona = Persona.from_dict(data)

    assert persona.name == "Test Persona"
    assert persona.description == ""
    assert persona.system_prompt == ""
    assert persona.personality == ""
    assert persona.avatar_url is None
    assert persona.after_context is None
    assert persona.history_limit is None
    assert persona.first_message is None
    assert persona.examples == []
    assert persona.allow_summon is False


def test_persona_from_dict_full() -> None:
    data = {
        "name": "Full",
        "description": "Desc",
        "system_prompt": "Sys",
        "personality": "Pers",
        "avatar_url": "Url",
        "after_context": "After",
        "history_limit": "42",
        "first_message": "Hello",
        "examples": [{"user": "hi", "bot": "hello"}],
        "allow_summon": True,
    }
    persona = Persona.from_dict(data)

    assert persona.name == "Full"
    assert persona.history_limit == 42
    assert persona.allow_summon is True
    assert persona.examples is not None
    assert len(persona.examples) == 1


def test_persona_from_dict_invalid_history_limit() -> None:
    data = {"name": "Bad", "history_limit": "NotAnInt"}
    persona = Persona.from_dict(data)

    assert persona.history_limit is None


class TestPersonaManager:
    @pytest.fixture
    def data_dir(self, tmp_path: Path) -> str:
        # Create some fake persona files
        p1 = tmp_path / "valid1.json"
        p1.write_text(json.dumps({"name": "Valid 1", "allow_summon": True}))

        p2 = tmp_path / "valid2.json"
        p2.write_text(json.dumps({"name": "Valid 2", "allow_summon": False}))

        p3 = tmp_path / "not_json.txt"
        p3.write_text("Should be ignored")

        return str(tmp_path)

    def test_list_personas(self, data_dir: str) -> None:
        manager = PersonaManager(data_dir)
        personas = manager.list_personas()

        assert len(personas) == 2
        assert set(personas) == {"valid1", "valid2"}

    def test_list_personas_no_dir(self, tmp_path: Path) -> None:
        manager = PersonaManager(str(tmp_path / "does_not_exist"))
        assert manager.list_personas() == []

    def test_load_persona(self, data_dir: str) -> None:
        manager = PersonaManager(data_dir)
        persona = manager.load_persona("valid1")

        assert persona is not None
        assert persona.name == "Valid 1"
        assert persona.allow_summon is True

    def test_load_persona_not_found(self, data_dir: str) -> None:
        manager = PersonaManager(data_dir)
        assert manager.load_persona("nonexistent") is None

    def test_load_persona_path_traversal(self, data_dir: str) -> None:
        manager = PersonaManager(data_dir)
        # Assuming the manager protects against path traversal;
        # if it doesn't, this test will fail and alert us we should fix it,
        # but let's test typical sanitization.
        assert manager.load_persona("../valid1") is None
        assert manager.load_persona("..\\valid1") is None
        assert manager.load_persona("/etc/passwd") is None

    def test_get_summonable_personas(self, data_dir: str) -> None:
        manager = PersonaManager(data_dir)
        app_commands_choices = manager.get_summonable_personas()

        # Should only return valid1 since valid2 allow_summon=False
        assert len(app_commands_choices) == 1
        assert app_commands_choices[0] == "valid1"

        # Test cache works
        assert manager._summonable_cache is not None
        manager._summonable_cache.append("fake_cached_item")

        app_commands_choices2 = manager.get_summonable_personas()
        assert "fake_cached_item" in app_commands_choices2
