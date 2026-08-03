"""Config schema versioning and migrations for Profile.

Migrations are additive, idempotent, and rollback-safe: legacy keys are never
removed, so rolling back to earlier code never loses data. Each step runs only
when the stored version is below its target and the record is stamped
afterwards.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("red.kirin_cogs.profile.migrations")

#: Current global-scope schema version. Bump when adding a migration step.
GLOBAL_SCHEMA_VERSION = 1


def normalize_version(value: Any) -> int:
    """Return a usable schema version, treating malformed values as legacy v0."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


async def migrate_global_schema(config: Any) -> None:
    """Bring the global record up to :data:`GLOBAL_SCHEMA_VERSION`.

    ``config`` is a :class:`redbot.core.Config` in production (global values
    are plain attribute access) and a ``testutils.migration.DictConfig`` in
    tests. v0 → v1 is marker-only; later migration steps are appended before
    the stamping write.
    """
    version = normalize_version(await config.schema_version())
    if version >= GLOBAL_SCHEMA_VERSION:
        return
    await config.schema_version.set(GLOBAL_SCHEMA_VERSION)
    log.info("Migrated global config schema v%s -> v%s", version, GLOBAL_SCHEMA_VERSION)
