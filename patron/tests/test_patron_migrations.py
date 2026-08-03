"""Rollback-safe migration fixtures and version-marker tests for Patron."""

from typing import Any

import pytest

from patron.migrations import GUILD_SCHEMA_VERSION, migrate_guild_schemas
from testutils.migration import DictConfig, assert_idempotent, historical_variants

# Representative pre-migration (v0) guild record: everything Patron stored
# before schema version markers existed.
LEGACY_GUILD_RECORD: dict[str, Any] = {
    "sheet_id": "sheet123",
    "role_active": 10,
    "role_former": 20,
    "log_channel": 30,
    "processed_charges": {"alice": "2024-01-01", "bob": "2024-02-15"},
    "annual_tracking": {
        "alice": {"anchor_date": "2024-01-01T00:00:00", "months_paid": 2, "last_award": "2024-02-01T00:00:00"}
    },
}

PATRON_GUILD_DEFAULTS = {
    "schema_version": 0,
    "sheet_id": None,
    "role_active": None,
    "role_former": None,
    "log_channel": None,
    "processed_charges": {},
    "annual_tracking": {},
}

GUILD_ID = 1234


def _config(record: dict[str, Any] | None = None) -> DictConfig:
    data = dict(LEGACY_GUILD_RECORD) if record is None else record
    return DictConfig({"guild": {GUILD_ID: data}})


def _assert_rollback_safe(original: dict[str, Any], migrated: dict[str, Any]) -> None:
    """Every legacy key must survive migration so a rollback loses nothing."""
    for key, value in original.items():
        assert migrated.get(key) == value


@pytest.mark.asyncio
async def test_stamps_schema_version_on_legacy_record() -> None:
    config = _config()
    await migrate_guild_schemas(config)
    assert config.guild_from_id(GUILD_ID).raw()["schema_version"] == GUILD_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_migration_is_idempotent() -> None:
    await assert_idempotent(migrate_guild_schemas, _config())


@pytest.mark.asyncio
async def test_migration_preserves_legacy_keys() -> None:
    config = _config()
    await migrate_guild_schemas(config)
    _assert_rollback_safe(LEGACY_GUILD_RECORD, config.guild_from_id(GUILD_ID).raw())


@pytest.mark.asyncio
async def test_migration_skips_current_records() -> None:
    record = dict(LEGACY_GUILD_RECORD)
    record["schema_version"] = GUILD_SCHEMA_VERSION
    config = _config(record)
    await migrate_guild_schemas(config)
    assert config.guild_from_id(GUILD_ID).raw() == record


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot",
    historical_variants(PATRON_GUILD_DEFAULTS, scope="guild", record_id=99),
    ids=lambda s: repr(s)[:60],
)
async def test_migration_tolerates_malformed_history(snapshot: dict[str, Any]) -> None:
    await assert_idempotent(migrate_guild_schemas, DictConfig(snapshot))
