"""Scriptless automod editing: HTML form fields to rule rows and back, and read-only descriptions.

The row types come from the AutoMod cog's registry (`cog.registry`, automod/types.py), so the site never imports
another cog's package directly.
"""

from collections.abc import Callable, Mapping
from typing import Any

SECTIONS = ("triggers", "conditions", "effects")
MAX_ROWS = 50


def parse_rows(form: Any, registry: Any, section: str) -> list[dict]:
    """Rows as submitted, unvalidated. Unknown types are kept so validation can name them."""
    rows = []
    for n in range(MAX_ROWS):
        prefix = f"{section}-{n}-"
        kind = form.get(prefix + "type")
        if kind is None:
            break
        row: dict[str, Any] = {"type": str(kind)}
        row_type = registry.SECTIONS[section].get(row["type"])
        for field in row_type.fields if row_type else ():
            name = prefix + field.name
            if field.kind == "bool":
                row[field.name] = name in form
            elif field.kind in ("roles", "channels"):
                row[field.name] = [str(v) for v in form.getall(name, [])]
            else:
                row[field.name] = str(form.get(name, ""))
        rows.append(row)
    return rows


def new_row(registry: Any, section: str, kind: str) -> dict | None:
    row_type = registry.SECTIONS[section].get(kind)
    if row_type is None:
        return None
    return {"type": kind, **{f.name: f.default for f in row_type.fields}}


def apply_action(action: str, draft: dict, form: Any, registry: Any, sections: tuple[str, ...]) -> bool:
    """Add or remove a row in the draft for an `add-<section>` / `remove-<section>-<n>` button.

    Returns False when the action isn't one of those.
    """
    for section in sections:
        if action == f"add-{section}":
            row = new_row(registry, section, str(form.get(f"new-{section}", "")))
            if row is not None and len(draft[section]) < MAX_ROWS:
                draft[section].append(row)
            return True
        prefix = f"remove-{section}-"
        if action.startswith(prefix) and action[len(prefix) :].isdigit():
            index = int(action[len(prefix) :])
            if index < len(draft[section]):
                del draft[section][index]
            return True
    return False


class Names:
    """Current role, channel and list names, with deleted ones shown by ID."""

    def __init__(self, roles: Mapping[int, str], channels: Mapping[int, str], lists: Mapping[int, str]) -> None:
        self.roles, self.channels, self.lists = roles, channels, lists

    def role(self, role_id: int) -> str:
        return f"@{self.roles[role_id]}" if role_id in self.roles else f"Deleted role {role_id}"

    def channel(self, channel_id: int) -> str:
        return f"#{self.channels[channel_id]}" if channel_id in self.channels else f"Deleted channel {channel_id}"

    def render(self, kind: str, value: Any) -> str:
        if kind == "roles":
            return ", ".join(self.role(_as_int(v)) for v in value)
        if kind == "channels":
            return ", ".join(self.channel(_as_int(v)) for v in value)
        if kind == "channel":
            return self.channel(_as_int(value)) if _as_int(value) else "the event's channel"
        if kind == "list":
            return f"list “{self.lists.get(_as_int(value), f'#{value}')}”"
        if kind == "bool":
            return "yes" if value else "no"
        return str(value)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _options(names: Mapping[int, str], chosen: set[int], label: Callable[[int], str]) -> list[dict]:
    """Every current choice, plus chosen ones that no longer exist, so saving never drops them silently."""
    ids = [*names, *sorted(chosen - set(names))]
    return [{"value": str(i), "label": label(i), "checked": i in chosen} for i in ids]


def row_view(registry: Any, section: str, n: int, row: dict, names: Names) -> dict:
    """What the templates need to show one row, read-only and as form inputs."""
    row_type = registry.SECTIONS[section].get(row.get("type"))
    view: dict[str, Any] = {
        "type": row.get("type"),
        "label": row_type.label if row_type else f"Unknown ({row.get('type')})",
        "text": registry.describe(section, row, names.render),
        "fields": [],
    }
    for field in row_type.fields if row_type else ():
        value = row.get(field.name, field.default)
        item: dict[str, Any] = {
            "name": f"{section}-{n}-{field.name}",
            "kind": field.kind,
            "label": field.label,
            "value": value,
            "min": field.min,
            "max": field.max,
        }
        if field.kind in ("roles", "channels"):
            chosen = {_as_int(v) for v in value} if isinstance(value, list) else set()
            source = names.roles if field.kind == "roles" else names.channels
            item["options"] = _options(source, chosen, names.role if field.kind == "roles" else names.channel)
        elif field.kind == "channel":
            chosen = {_as_int(value)} - {0}
            item["options"] = [
                {"value": "0", "label": "The event's channel", "checked": not chosen},
                *_options(names.channels, chosen, names.channel),
            ]
        elif field.kind == "list":
            chosen = {_as_int(value)} - {0}
            item["options"] = _options(names.lists, chosen, lambda i: names.lists.get(i, f"Deleted list {i}"))
        view["fields"].append(item)
    return view


def editor_view(registry: Any, draft: dict, names: Names, sections: tuple[str, ...]) -> dict:
    """A rule or ruleset draft as sections of row views, plus the types that can be added."""
    return {
        section: {
            "rows": [row_view(registry, section, n, row, names) for n, row in enumerate(draft[section])],
            "types": [(key, t.label) for key, t in registry.SECTIONS[section].items()],
            "singular": registry.SINGULAR[section],
        }
        for section in sections
    }
