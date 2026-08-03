"""Config schema versioning and migrations for AntiNuke.

Migrations are additive, idempotent, and rollback-safe: legacy keys are never
removed, so rolling back to earlier code never loses data. Each step runs only
for records below its version and the record is stamped afterwards.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

log = logging.getLogger("red.kirin-cogs.antinuke.migrations")


class GuildConfigLike(Protocol):
    """Subset of :class:`redbot.core.Config` used by guild-scope migrations.

    Also satisfied by ``testutils.migration.DictConfig`` in tests.
    """

    async def all_guilds(self) -> dict[int, Any]: ...
    def guild_from_id(self, guild_id: int) -> Any: ...


#: Current guild-scope schema version. Bump when adding a migration step.
GUILD_SCHEMA_VERSION = 1


def normalize_version(value: Any) -> int:
    """Return a usable schema version, treating malformed values as legacy v0."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


async def migrate_guild_schemas(config: GuildConfigLike) -> None:
    """Bring every stored guild record up to :data:`GUILD_SCHEMA_VERSION`.

    v0 → v1 is marker-only; later migration steps are appended before the
    stamping write.
    """
    guilds = await config.all_guilds()
    for guild_id, data in guilds.items():
        if not isinstance(data, dict):
            log.warning("Skipping malformed guild record %s during schema migration", guild_id)
            continue
        version = normalize_version(data.get("schema_version"))
        if version >= GUILD_SCHEMA_VERSION:
            continue
        await config.guild_from_id(guild_id).schema_version.set(GUILD_SCHEMA_VERSION)
        log.info(
            "Migrated guild %s config schema v%s -> v%s",
            guild_id,
            version,
            GUILD_SCHEMA_VERSION,
        )
