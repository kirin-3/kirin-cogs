"""Reusable helpers for testing idempotent Red Config migrations.

Cog migrations run against :class:`redbot.core.Config`. The classes here provide
a minimal dict-backed stand-in (:class:`DictConfig`) so migrations can be executed
repeatedly against historical data shapes — missing keys, ``None``, empty
containers, and malformed values — without a running Red instance.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from copy import deepcopy
from typing import Any

__all__ = [
    "DictConfig",
    "DictGroup",
    "DictValue",
    "assert_idempotent",
    "historical_variants",
]

MigrationFn = Callable[["DictConfig"], Awaitable[None]]


class DictValue:
    """Mimics a Red Config value accessor.

    ``await value()`` returns a copy of the stored value and
    ``await value.set(v)`` stores a copy, mirroring Config semantics.
    """

    def __init__(self, store: dict[str, Any], key: str) -> None:
        self._store = store
        self._key = key

    async def __call__(self) -> Any:
        return deepcopy(self._store.get(self._key))

    async def set(self, value: Any) -> None:
        self._store[self._key] = deepcopy(value)

    async def clear(self) -> None:
        self._store.pop(self._key, None)


class _GroupContext:
    """Async context manager yielding a group's raw mutable mapping."""

    def __init__(self, store: dict[str, Any]) -> None:
        self._store = store

    async def __aenter__(self) -> dict[str, Any]:
        return self._store

    async def __aexit__(self, *exc: object) -> None:
        return None


class DictGroup:
    """Attribute access to values within one Config scope record."""

    def __init__(self, store: dict[str, Any]) -> None:
        self._store = store

    def __getattr__(self, name: str) -> DictValue:
        if name.startswith("_"):
            raise AttributeError(name)
        return DictValue(self._store, name)

    def __call__(self) -> _GroupContext:
        return _GroupContext(self._store)

    async def all(self) -> dict[str, Any]:
        return deepcopy(self._store)

    async def set(self, value: dict[str, Any]) -> None:
        """Replace the whole group record (mirrors Red's ``Group.set``)."""
        self._store.clear()
        self._store.update(deepcopy(value))

    def raw(self) -> dict[str, Any]:
        """Direct access to the underlying store (test assertions only)."""
        return self._store


def _identity(obj: Any) -> int:
    """Extract an integer id from a discord-like object or a raw id."""
    return int(getattr(obj, "id", obj))


class DictConfig:
    """Dict-backed subset of :class:`redbot.core.Config` for migration tests.

    Snapshot shape::

        {
            "global": {...},
            "guild": {guild_id: {...}},
            "user": {user_id: {...}},
            "member": {guild_id: {member_id: {...}}},
        }
    """

    def __init__(self, snapshot: dict[str, Any] | None = None) -> None:
        snap = deepcopy(snapshot) if snapshot else {}
        self._global: dict[str, Any] = snap.get("global") or {}
        self._guilds: dict[int, dict[str, Any]] = {int(g): (v or {}) for g, v in (snap.get("guild") or {}).items()}
        self._users: dict[int, dict[str, Any]] = {int(u): (v or {}) for u, v in (snap.get("user") or {}).items()}
        self._members: dict[int, dict[int, dict[str, Any]]] = {
            int(g): {int(m): (v or {}) for m, v in (members or {}).items()}
            for g, members in (snap.get("member") or {}).items()
        }

    # -- global scope (Config exposes global values on the instance) ---------

    def __getattr__(self, name: str) -> DictValue:
        if name.startswith("_"):
            raise AttributeError(name)
        return DictValue(self._global, name)

    def __call__(self) -> _GroupContext:
        return _GroupContext(self._global)

    # -- scoped groups --------------------------------------------------------

    def guild(self, guild: Any) -> DictGroup:
        return self.guild_from_id(_identity(guild))

    def guild_from_id(self, guild_id: int) -> DictGroup:
        return DictGroup(self._guilds.setdefault(int(guild_id), {}))

    def user(self, user: Any) -> DictGroup:
        return self.user_from_id(_identity(user))

    def user_from_id(self, user_id: int) -> DictGroup:
        return DictGroup(self._users.setdefault(int(user_id), {}))

    def member(self, member: Any) -> DictGroup:
        guild_id = _identity(getattr(member, "guild", 0))
        return self.member_from_ids(guild_id, _identity(member))

    def member_from_ids(self, guild_id: int, member_id: int) -> DictGroup:
        guild_members = self._members.setdefault(int(guild_id), {})
        return DictGroup(guild_members.setdefault(int(member_id), {}))

    # -- bulk reads (deep copies, matching Red semantics) ---------------------

    async def all(self) -> dict[str, Any]:
        return deepcopy(self._global)

    async def all_guilds(self) -> dict[int, dict[str, Any]]:
        return deepcopy(self._guilds)

    async def all_users(self) -> dict[int, dict[str, Any]]:
        return deepcopy(self._users)

    async def all_members(self) -> dict[int, dict[int, dict[str, Any]]]:
        return deepcopy(self._members)

    # -- test support -----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a deep copy of every scope for equality assertions."""
        return {
            "global": deepcopy(self._global),
            "guild": deepcopy(self._guilds),
            "user": deepcopy(self._users),
            "member": deepcopy(self._members),
        }


async def assert_idempotent(migration: MigrationFn, config: DictConfig) -> None:
    """Run ``migration`` twice and assert the second run changes nothing."""
    await migration(config)
    first = config.snapshot()
    await migration(config)
    second = config.snapshot()
    assert first == second, "migration is not idempotent: second run mutated state"


def historical_variants(
    defaults: dict[str, Any],
    *,
    scope: str = "guild",
    record_id: int = 1,
    malformed_values: Iterable[Any] = (None, "", [], {}, "malformed"),
) -> list[dict[str, Any]]:
    """Build DictConfig snapshots covering hostile historical data.

    ``defaults`` is the cog's registered-default mapping for one record in the
    given scope. The returned snapshots cover: the record being absent, the
    record being empty, each default key holding a ``None``/empty/malformed
    value, and an unrelated garbage key. Every variant is a valid input for
    :class:`DictConfig`.
    """
    variants: list[dict[str, Any]] = [
        {},
        {scope: {record_id: {}}},
        {scope: {record_id: {"totally_unrelated": {"nested": [1, 2, 3]}}}},
    ]
    for key in defaults:
        for bad in malformed_values:
            variants.append({scope: {record_id: {key: bad}}})
    return variants
