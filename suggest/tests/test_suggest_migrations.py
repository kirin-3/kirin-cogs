"""Rollback-safe migration fixtures and version-marker tests for Suggest."""

from typing import Any

import pytest

from suggest.migrations import GLOBAL_SCHEMA_VERSION, migrate_global_schema
from testutils.migration import DictConfig, assert_idempotent

# Representative pre-migration (v0) global record: everything Suggest stored
# before schema version markers existed.
LEGACY_GLOBAL_RECORD: dict[str, Any] = {
    "next_id": 140,
    "sticky_message_id": 77,
}


def _config(global_record: dict[str, Any] | None = None) -> DictConfig:
    g = dict(LEGACY_GLOBAL_RECORD) if global_record is None else global_record
    return DictConfig({"global": g})


@pytest.mark.asyncio
async def test_stamps_schema_version_on_legacy_install() -> None:
    config = _config()
    await migrate_global_schema(config)
    assert await config.schema_version() == GLOBAL_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_migration_is_idempotent() -> None:
    await assert_idempotent(migrate_global_schema, _config())


@pytest.mark.asyncio
async def test_migration_preserves_legacy_keys() -> None:
    """Legacy keys survive migration so a rollback loses nothing."""
    config = _config()
    await migrate_global_schema(config)
    snapshot = config.snapshot()
    for key, value in LEGACY_GLOBAL_RECORD.items():
        assert snapshot["global"].get(key) == value


@pytest.mark.asyncio
async def test_migration_skips_current_install() -> None:
    config = _config(global_record={**LEGACY_GLOBAL_RECORD, "schema_version": GLOBAL_SCHEMA_VERSION})
    before = config.snapshot()
    await migrate_global_schema(config)
    assert config.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", [], {}, "malformed", -1, True], ids=repr)
async def test_migration_tolerates_malformed_version(bad: Any) -> None:
    config = _config(global_record={"schema_version": bad})
    await assert_idempotent(migrate_global_schema, config)
    assert await config.schema_version() == GLOBAL_SCHEMA_VERSION


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "132", [], {}, True, -5], ids=repr)
async def test_migration_normalizes_malformed_next_id_even_at_current_version(bad: Any) -> None:
    config = _config(global_record={"schema_version": GLOBAL_SCHEMA_VERSION, "next_id": bad})
    await assert_idempotent(migrate_global_schema, config)
    assert await config.next_id() == 132
