"""Rollback-safe migration fixtures and version-marker tests for Profile."""

from profile.migrations import GLOBAL_SCHEMA_VERSION, migrate_global_schema
from typing import Any

import pytest

from testutils.migration import DictConfig, assert_idempotent

# Representative pre-migration (v0) records: global channel config plus
# user-scope profile answers, before schema version markers existed.
LEGACY_GLOBAL_RECORD: dict[str, Any] = {
    "channel_id": 686091267012296714,
    "sticky_message_id": 555,
    "sticky_locked": True,
    "cooldown": 5,
}
LEGACY_USER_RECORD: dict[str, Any] = {
    "profile_data": {"nickname": "Tester", "age": "30", "picture": "https://example.com/legacy.png"},
    "message_id": 987,
    "last_delete": "2024-01-01T00:00:00",
}

USER_ID = 777


def _config(
    global_record: dict[str, Any] | None = None,
    user_record: dict[str, Any] | None = None,
) -> DictConfig:
    g = dict(LEGACY_GLOBAL_RECORD) if global_record is None else global_record
    u = dict(LEGACY_USER_RECORD) if user_record is None else user_record
    return DictConfig({"global": g, "user": {USER_ID: u}})


@pytest.mark.asyncio
async def test_stamps_schema_version_on_legacy_install() -> None:
    config = _config()
    await migrate_global_schema(config)
    assert await config.schema_version() == GLOBAL_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_migration_is_idempotent() -> None:
    await assert_idempotent(migrate_global_schema, _config())


@pytest.mark.asyncio
async def test_migration_preserves_legacy_records() -> None:
    """Legacy global and user-scope records survive so a rollback loses nothing."""
    config = _config()
    await migrate_global_schema(config)
    snapshot = config.snapshot()
    for key, value in LEGACY_GLOBAL_RECORD.items():
        assert snapshot["global"].get(key) == value
    assert snapshot["user"][USER_ID] == LEGACY_USER_RECORD


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
