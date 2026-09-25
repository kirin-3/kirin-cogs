"""Every trigger, condition and effect type, and validation of the rules document.

Validation, the staff site's forms and its read-only descriptions all come from this registry,
so adding a type means adding one entry here and its behaviour in engine.py / automod.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import regex

# Field kinds: text, regex, int, bool, roles, channels, channel (0 = none), list (a list's id).
MAX_REGEX = 1000
MAX_WORDS = 5000
MAX_WORD = 100


class RuleError(ValueError):
    """A rules document that can't be saved; the message names the ruleset, rule and row."""


@dataclass(frozen=True)
class Field:
    name: str
    kind: str
    label: str
    default: Any
    min: int = 0
    max: int = 0  # int range, or text length


@dataclass(frozen=True)
class RowType:
    key: str
    label: str
    template: str  # read-only sentence; {field} placeholders
    fields: tuple[Field, ...] = ()
    group: str = ""  # triggers: message, counted or name


def _count(lo: int = 2) -> Field:
    return Field("count", "int", "Count", max(lo, 5), lo, 100)


SECONDS = Field("seconds", "int", "Seconds", 10, 1, 3600)
PATTERN = Field("pattern", "regex", "Pattern", "")
LIST = Field("list", "list", "List", 0)
REASON = Field("reason", "text", "Reason (empty: automod default)", "", 0, 500)

TRIGGERS: dict[str, RowType] = {
    t.key: t
    for t in (
        RowType("regex", "Regex match", "Message matches `{pattern}`", (PATTERN,), "message"),
        RowType("not_regex", "Regex no-match", "Message does not match `{pattern}`", (PATTERN,), "message"),
        RowType("words", "Word list", "Message contains a word from {list}", (LIST,), "message"),
        RowType("invite", "Server invite", "Message contains a server invite", (), "message"),
        RowType("link", "Any link", "Message contains a link", (), "message"),
        RowType(
            "mentions",
            "Mentions",
            "Message mentions {count} or more different users and roles",
            (_count(1),),
            "message",
        ),
        RowType("message_rate", "Messages", "{count} messages within {seconds} s", (_count(), SECONDS), "counted"),
        RowType(
            "duplicates",
            "Identical messages",
            "{count} identical messages within {seconds} s (any channel: {any_channel})",
            (_count(), SECONDS, Field("any_channel", "bool", "Count other channels", False)),
            "counted",
        ),
        RowType(
            "attachment_rate",
            "Attachments",
            "{count} attachments within {seconds} s (every file counts: {per_attachment})",
            (_count(), SECONDS, Field("per_attachment", "bool", "Count every file in a message", False)),
            "counted",
        ),
        RowType("link_rate", "Links", "{count} links within {seconds} s", (_count(), SECONDS), "counted"),
        RowType(
            "mention_rate",
            "Mentions over time",
            "{count} mentions within {seconds} s (repeats count: {repeats})",
            (_count(), SECONDS, Field("repeats", "bool", "Count repeated mentions", False)),
            "counted",
        ),
        RowType("name_regex", "Name regex", "A name matches `{pattern}`", (PATTERN,), "name"),
        RowType("name_words", "Name word list", "A name contains a word from {list}", (LIST,), "name"),
    )
}

CONDITIONS: dict[str, RowType] = {
    t.key: t
    for t in (
        RowType("ignore_bots", "Ignore bots", "Member is not a bot"),
        RowType("ignore_roles", "Ignore roles", "Member has none of {roles}", (Field("roles", "roles", "Roles", []),)),
        RowType(
            "require_roles",
            "Require roles",
            "Member has {mode} {roles}",
            (Field("roles", "roles", "Roles", []), Field("all", "bool", "Require all of them", False)),
        ),
        RowType(
            "ignore_channels",
            "Ignore channels",
            "Not in {channels}",
            (Field("channels", "channels", "Channels", []),),
        ),
        RowType(
            "only_channels",
            "Only in channels",
            "Only in {channels}",
            (Field("channels", "channels", "Channels", []),),
        ),
        RowType("new_only", "New messages only", "Only new messages"),
        RowType("edits_only", "Edits only", "Only edited messages"),
    )
}

EFFECTS: dict[str, RowType] = {
    t.key: t
    for t in (
        RowType("delete", "Delete message", "Delete the message"),
        RowType("warn", "Warn", "Warn: {reason}", (REASON,)),
        RowType(
            "mute",
            "Mute",
            "Mute for {minutes} min (0 = until unmuted): {reason}",
            (Field("minutes", "int", "Minutes (0: until unmuted)", 60, 0, 525600), REASON),
        ),
        RowType(
            "timeout",
            "Timeout",
            "Time out for {minutes} min: {reason}",
            (Field("minutes", "int", "Minutes", 60, 1, 40320), REASON),
        ),
        RowType(
            "ban",
            "Ban",
            "Ban, deleting {delete_days} day(s) of messages: {reason}",
            (Field("delete_days", "int", "Days of messages to delete", 0, 0, 7), REASON),
        ),
        RowType(
            "nickname",
            "Set nickname",
            "Set nickname to {nickname}",
            (Field("nickname", "text", "Nickname", "Change your nickname", 1, 32),),
        ),
        RowType(
            "send",
            "Send message",
            "Send to {channel} (ping: {ping}, delete after {delete_after} s): {text}",
            (
                Field("channel", "channel", "Channel (none: the event's channel)", 0),
                Field("text", "text", "Text", "", 1, 2000),
                Field("ping", "bool", "Mention the member", False),
                Field("delete_after", "int", "Delete after seconds (0: keep)", 0, 0, 3600),
            ),
        ),
    )
}

SECTIONS: dict[str, dict[str, RowType]] = {"triggers": TRIGGERS, "conditions": CONDITIONS, "effects": EFFECTS}
SINGULAR = {"triggers": "trigger", "conditions": "condition", "effects": "effect"}


def describe(section: str, row: dict, render: Callable[[str, Any], str] = lambda kind, value: str(value)) -> str:
    """The read-only sentence for a row; `render(kind, value)` formats roles, channels and lists."""
    kind = SECTIONS[section].get(row.get("type", ""))
    if kind is None:
        return f"Unknown {SINGULAR[section]} {row.get('type')!r}"
    values = {f.name: render(f.kind, row.get(f.name, f.default)) for f in kind.fields}
    if kind.key == "require_roles":
        values["mode"] = "all of" if row.get("all") else "any of"
    return kind.template.format(**values)


# --- validation ----------------------------------------------------------------------------------


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _ids(value: Any) -> list[int] | None:
    if not isinstance(value, list):
        return None
    ids = [_int(v) for v in value]
    if any(i is None or i <= 0 for i in ids):
        return None
    return list(dict.fromkeys(i for i in ids if i is not None))


def _name(value: Any, where: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100:
        raise RuleError(f"{where}: the name must be 1 to 100 characters.")
    return value.strip()


def _field(field: Field, value: Any, list_ids: set[int], where: str) -> Any:
    label = f"{where}, {field.label.lower()}"
    if field.kind == "bool":
        if not isinstance(value, bool):
            raise RuleError(f"{label}: must be true or false.")
        return value
    if field.kind in ("int", "channel", "list"):
        number = _int(value)
        if field.kind == "int" and (number is None or not field.min <= number <= field.max):
            raise RuleError(f"{label}: must be a whole number from {field.min} to {field.max}.")
        if field.kind == "channel" and (number is None or number < 0):
            raise RuleError(f"{label}: must be a channel ID.")
        if field.kind == "list" and number not in list_ids:
            raise RuleError(f"{label}: pick an existing list.")
        return number
    if field.kind in ("roles", "channels"):
        ids = _ids(value)
        if not ids:
            raise RuleError(f"{label}: pick at least one.")
        return ids
    if not isinstance(value, str):
        raise RuleError(f"{label}: must be text.")
    if field.kind == "regex":
        if not 1 <= len(value) <= MAX_REGEX:
            raise RuleError(f"{label}: must be 1 to {MAX_REGEX} characters.")
        try:
            regex.compile(value)
        except regex.error as e:
            raise RuleError(f"{label}: invalid regex ({e}).")
        return value
    if not field.min <= len(value.strip()) <= field.max:
        raise RuleError(f"{label}: must be {field.min} to {field.max} characters.")
    return value.strip()


def validate_row(section: str, row: Any, list_ids: set[int], where: str) -> dict:
    """One trigger, condition or effect, with defaults filled in and unknown keys dropped."""
    singular = SINGULAR[section]
    if not isinstance(row, dict) or row.get("type") not in SECTIONS[section]:
        raise RuleError(f"{where}: unknown {singular} type {row.get('type') if isinstance(row, dict) else row!r}.")
    kind = SECTIONS[section][row["type"]]
    where = f"{where} ({kind.label})"
    out: dict[str, Any] = {"type": kind.key}
    for field in kind.fields:
        out[field.name] = _field(field, row.get(field.name, field.default), list_ids, where)
    return out


def _rows(section: str, rows: Any, list_ids: set[int], where: str) -> list[dict]:
    if not isinstance(rows, list):
        raise RuleError(f"{where}: {section} must be a list.")
    return [validate_row(section, row, list_ids, f"{where}, {SINGULAR[section]} {n}") for n, row in enumerate(rows, 1)]


def _id(value: Any, seen: set[int], where: str) -> int:
    number = _int(value)
    if number is None or number <= 0 or number in seen:
        raise RuleError(f"{where}: missing or duplicate id.")
    seen.add(number)
    return number


def validate(document: Any) -> dict:
    """Check a whole rules document and return it normalized. Raises RuleError on the first problem."""
    if not isinstance(document, dict):
        raise RuleError("The rules file must be a JSON object.")
    raw_lists, raw_rulesets = document.get("lists", []), document.get("rulesets", [])
    if not isinstance(raw_lists, list) or not isinstance(raw_rulesets, list):
        raise RuleError("`lists` and `rulesets` must be lists.")
    seen: set[int] = set()

    lists = []
    for n, item in enumerate(raw_lists, 1):
        if not isinstance(item, dict):
            raise RuleError(f"List {n}: must be an object.")
        name = _name(item.get("name"), f"List {n}")
        where = f"List {name!r}"
        words = item.get("words", [])
        if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
            raise RuleError(f"{where}: words must be text.")
        words = list(dict.fromkeys(w.strip() for w in words if w.strip()))
        if len(words) > MAX_WORDS or any(len(w) > MAX_WORD for w in words):
            raise RuleError(f"{where}: at most {MAX_WORDS} entries of up to {MAX_WORD} characters.")
        lists.append({"id": _id(item.get("id"), seen, where), "name": name, "words": words})
    list_ids = {item["id"] for item in lists}

    rulesets = []
    for n, item in enumerate(raw_rulesets, 1):
        if not isinstance(item, dict):
            raise RuleError(f"Ruleset {n}: must be an object.")
        name = _name(item.get("name"), f"Ruleset {n}")
        where = f"Ruleset {name!r}"
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise RuleError(f"{where}: enabled must be true or false.")
        raw_rules = item.get("rules", [])
        if not isinstance(raw_rules, list):
            raise RuleError(f"{where}: rules must be a list.")
        ruleset = {
            "id": _id(item.get("id"), seen, where),
            "name": name,
            "enabled": enabled,
            "conditions": _rows("conditions", item.get("conditions", []), list_ids, where),
            "rules": [],
        }
        for m, rule in enumerate(raw_rules, 1):
            if not isinstance(rule, dict):
                raise RuleError(f"{where}, rule {m}: must be an object.")
            rule_name = _name(rule.get("name"), f"{where}, rule {m}")
            rule_where = f"{where}, rule {rule_name!r}"
            triggers = _rows("triggers", rule.get("triggers", []), list_ids, rule_where)
            if not triggers:
                raise RuleError(f"{rule_where}: needs at least one trigger.")
            ruleset["rules"].append(
                {
                    "id": _id(rule.get("id"), seen, rule_where),
                    "name": rule_name,
                    "triggers": triggers,
                    "conditions": _rows("conditions", rule.get("conditions", []), list_ids, rule_where),
                    "effects": _rows("effects", rule.get("effects", []), list_ids, rule_where),
                }
            )
        rulesets.append(ruleset)

    next_id = _int(document.get("next_id")) or 1
    return {"rulesets": rulesets, "lists": lists, "next_id": max(next_id, max(seen, default=0) + 1)}


def list_users(document: dict, list_id: int) -> list[str]:
    """`ruleset / rule` names of every rule with a word list trigger on this list."""
    return [
        f"{ruleset['name']} / {rule['name']}"
        for ruleset in document["rulesets"]
        for rule in ruleset["rules"]
        if any(t.get("list") == list_id for t in rule["triggers"])
    ]
