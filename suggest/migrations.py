"""Config schema versioning and migrations for Suggest.

Migrations are additive, idempotent, and rollback-safe: legacy keys are never
removed, so rolling back to earlier code never loses data. Each step runs only
when the stored version is below its target and the record is stamped
afterwards.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("red.kirin_cogs.suggest.migrations")

#: Current global-scope schema version. Bump when adding a migration step.
GLOBAL_SCHEMA_VERSION = 2


def normalize_version(value: Any) -> int:
    """Return a usable schema version, treating malformed values as legacy v0."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


async def migrate_global_schema(config: Any) -> None:
    """Bring the global record up to :data:`GLOBAL_SCHEMA_VERSION`.

    ``config`` is a :class:`redbot.core.Config` in production (global values
    are plain attribute access) and a ``testutils.migration.DictConfig`` in
    tests. The invariant repair runs even on a current schema marker so a
    manually corrupted ``next_id`` cannot prevent cog loading. Schema v2
    records that identifier normalization is part of the migration contract.
    """
    raw_next_id = await config.next_id()
    next_id = raw_next_id if isinstance(raw_next_id, int) and not isinstance(raw_next_id, bool) else 132
    next_id = max(132, next_id)
    if raw_next_id != next_id or isinstance(raw_next_id, bool):
        await config.next_id.set(next_id)

    version = normalize_version(await config.schema_version())
    if version >= GLOBAL_SCHEMA_VERSION:
        return
    await config.schema_version.set(GLOBAL_SCHEMA_VERSION)
    log.info("Migrated global config schema v%s -> v%s", version, GLOBAL_SCHEMA_VERSION)
