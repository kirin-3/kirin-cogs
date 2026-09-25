"""Small builders for rules documents in tests."""

from itertools import count

_ids = count(1)


def rule(name: str, triggers: list, effects: list | None = None, conditions: list | None = None) -> dict:
    return {
        "id": next(_ids),
        "name": name,
        "triggers": triggers,
        "conditions": conditions or [],
        "effects": effects or [],
    }


def ruleset(name: str, rules: list, conditions: list | None = None, enabled: bool = True) -> dict:
    return {"id": next(_ids), "name": name, "enabled": enabled, "conditions": conditions or [], "rules": rules}


def word_list(name: str, words: list[str], list_id: int) -> dict:
    return {"id": list_id, "name": name, "words": words}


def document(*rulesets: dict, lists: list | None = None) -> dict:
    return {"rulesets": list(rulesets), "lists": lists or [], "next_id": 1}
