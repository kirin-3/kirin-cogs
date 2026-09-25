import copy

import pytest

from automod.tests.helpers import document, rule, ruleset, word_list
from automod.types import RuleError, describe, list_users, validate

INVITE = {"type": "invite"}


def _one(effects=None, triggers=None, lists=None) -> dict:
    return document(
        ruleset("invite", [rule("invite", [INVITE] if triggers is None else triggers, effects)]), lists=lists
    )


def test_clean_document_passes_unchanged() -> None:
    doc = validate(
        _one(
            [{"type": "delete"}, {"type": "mute", "minutes": 1440, "reason": "Invite"}],
            [INVITE, {"type": "words", "list": 900}],
            [word_list("words", ["badword"], 900)],
        )
    )
    assert validate(copy.deepcopy(doc)) == doc
    assert doc["next_id"] > max(r["id"] for r in doc["rulesets"])
    # Missing fields get their defaults.
    assert doc["rulesets"][0]["rules"][0]["effects"][0] == {"type": "delete"}


@pytest.mark.parametrize(
    ("doc", "message"),
    [
        (_one(triggers=[]), "Ruleset 'invite', rule 'invite': needs at least one trigger."),
        (_one([{"type": "mute", "minutes": -1}]), "must be a whole number from 0 to 525600"),
        (_one([{"type": "timeout", "minutes": 0}]), "must be a whole number from 1 to 40320"),
        (_one([{"type": "ban", "delete_days": 8}]), "from 0 to 7"),
        (_one(triggers=[{"type": "words", "list": 5}]), "trigger 1 (Word list), list: pick an existing list."),
        (_one(triggers=[{"type": "regex", "pattern": "(unclosed"}]), "trigger 1 (Regex match), pattern: invalid regex"),
        (_one([{"type": "warn", "reason": "x" * 501}]), "must be 0 to 500 characters"),
        (_one([{"type": "send", "text": ""}]), "must be 1 to 2000 characters"),
        (_one([{"type": "nickname", "nickname": "x" * 33}]), "must be 1 to 32 characters"),
        (_one([{"type": "explode"}]), "unknown effect type 'explode'"),
        (document(ruleset("x" * 101, [])), "Ruleset 1: the name must be 1 to 100 characters."),
        (_one(lists=[word_list("big", [str(n) for n in range(5001)], 900)]), "at most 5000 entries"),
        (_one(triggers=[{"type": "mentions", "count": "lots"}]), "must be a whole number"),
    ],
)
def test_invalid_documents_are_rejected_with_the_place(doc: dict, message: str) -> None:
    with pytest.raises(RuleError) as error:
        validate(doc)
    assert message in str(error.value)


def test_duplicate_ids_are_rejected() -> None:
    doc = _one()
    doc["rulesets"][0]["rules"][0]["id"] = doc["rulesets"][0]["id"]
    with pytest.raises(RuleError, match="duplicate id"):
        validate(doc)


def test_list_users_and_descriptions() -> None:
    doc = validate(_one(triggers=[{"type": "words", "list": 900}], lists=[word_list("slurs", ["x"], 900)]))
    assert list_users(doc, 900) == ["invite / invite"]
    assert list_users(doc, 901) == []
    row = {"type": "require_roles", "roles": [1, 2], "all": True}
    assert describe("conditions", row, lambda kind, v: "@A, @B" if kind == "roles" else str(v)) == (
        "Member has all of @A, @B"
    )


def test_odd_number_input_is_a_rule_error_not_a_crash() -> None:
    for value in ("²", "--5", "1.5", ""):
        with pytest.raises(RuleError, match="whole number"):
            validate(_one(triggers=[{"type": "mentions", "count": value}]))
