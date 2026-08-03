"""Config schema versioning and migrations for NitroAward.

Migrations are additive, idempotent, and rollback-safe: legacy keys are never
removed, so rolling back to earlier code never loses data. Each step runs only
when the stored version is below its target and the record is stamped
afterwards.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("red.kirin_cogs.nitroaward.migrations")

#: Current global-scope schema version. Bump when adding a migration step.
GLOBAL_SCHEMA_VERSION = 2


def normalize_version(value: Any) -> int:
    """Return a usable schema version, treating malformed values as legacy v0."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


async def _migrate_v1_to_v2(config: Any) -> None:
    """Move legacy global user-scope boost timestamps to a safe legacy record.

    v1 stored ``last_boost_timestamp`` in the global *user* scope, which let
    one guild's processing suppress another guild's award for the same user.
    The values are preserved in the global ``legacy_boost_records`` map
    (consulted only for exact boost-event matches) instead of being copied
    into per-guild member scope, which could wrongly suppress other guilds.
    The original user-scope keys are intentionally left in place so rolling
    back to v1 code loses nothing.
    """
    users = await config.all_users()
    if not isinstance(users, dict):
        users = {}

    moved: dict[str, float] = {}
    for user_id, data in users.items():
        if not isinstance(data, dict):
            continue
        ts = data.get("last_boost_timestamp")
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            continue
        moved[str(user_id)] = ts

    if moved:
        existing = await config.legacy_boost_records()
        if not isinstance(existing, dict):
            existing = {}
        # Do not overwrite entries a newer run already recorded.
        merged = {**moved, **existing}
        await config.legacy_boost_records.set(merged)
        log.info("Moved %d legacy boost record(s) out of the global user scope", len(moved))


async def migrate_global_schema(config: Any) -> None:
    """Bring the global record up to :data:`GLOBAL_SCHEMA_VERSION`.

    ``config`` is a :class:`redbot.core.Config` in production (global values
    are plain attribute access) and a ``testutils.migration.DictConfig`` in
    tests. Steps run in order and the record is stamped afterwards; every
    step is additive and idempotent.
    """
    version = normalize_version(await config.schema_version())
    if version < 2:
        await _migrate_v1_to_v2(config)
    if version >= GLOBAL_SCHEMA_VERSION:
        return
    await config.schema_version.set(GLOBAL_SCHEMA_VERSION)
    log.info("Migrated global config schema v%s -> v%s", version, GLOBAL_SCHEMA_VERSION)
