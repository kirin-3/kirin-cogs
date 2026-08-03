"""Rollback-safe migration fixtures and version-marker tests for NitroAward."""

from typing import Any

import pytest

from nitroaward.migrations import GLOBAL_SCHEMA_VERSION, migrate_global_schema
from testutils.migration import DictConfig, assert_idempotent

# Representative pre-migration (v1) user record: boost timestamps in the
# legacy global user scope.
LEGACY_USER_RECORD: dict[str, Any] = {"last_boost_timestamp": 1_700_000_000.5}

USER_ID = 555


def _config(user_record: dict[str, Any] | None = None) -> DictConfig:
    data = dict(LEGACY_USER_RECORD) if user_record is None else user_record
    return DictConfig({"user": {USER_ID: data}})


@pytest.mark.asyncio
async def test_stamps_schema_version_on_legacy_install() -> None:
    config = _config()
    await migrate_global_schema(config)
    assert await config.schema_version() == GLOBAL_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_migration_is_idempotent() -> None:
    await assert_idempotent(migrate_global_schema, _config())


@pytest.mark.asyncio
async def test_v2_moves_user_timestamps_to_legacy_record() -> None:
    config = _config()
    await migrate_global_schema(config)
    legacy = await config.legacy_boost_records()
    assert legacy == {str(USER_ID): LEGACY_USER_RECORD["last_boost_timestamp"]}


@pytest.mark.asyncio
async def test_v2_preserves_legacy_user_data_for_rollback() -> None:
    """The original user-scope keys are left in place so a rollback loses nothing."""
    config = _config()
    await migrate_global_schema(config)
    assert config.user_from_id(USER_ID).raw() == LEGACY_USER_RECORD


@pytest.mark.asyncio
async def test_v2_does_not_overwrite_existing_legacy_entries() -> None:
    config = DictConfig(
        {
            "global": {"legacy_boost_records": {str(USER_ID): 9_999_999_999.0}},
            "user": {USER_ID: dict(LEGACY_USER_RECORD)},
        }
    )
    await migrate_global_schema(config)
    legacy = await config.legacy_boost_records()
    assert legacy[str(USER_ID)] == 9_999_999_999.0


@pytest.mark.asyncio
async def test_migration_skips_current_install() -> None:
    config = DictConfig(
        {
            "global": {"schema_version": GLOBAL_SCHEMA_VERSION},
            "user": {USER_ID: dict(LEGACY_USER_RECORD)},
        }
    )
    before = config.snapshot()
    await migrate_global_schema(config)
    assert config.snapshot() == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_data",
    [
        None,
        {},
        {"last_boost_timestamp": None},
        {"last_boost_timestamp": "malformed"},
        {"last_boost_timestamp": [1, 2]},
        {"last_boost_timestamp": True},
        {"unrelated": 1},
    ],
    ids=repr,
)
async def test_v2_tolerates_malformed_user_data(user_data: Any) -> None:
    config = DictConfig({"user": {USER_ID: user_data}})
    await assert_idempotent(migrate_global_schema, config)
    legacy = await config.legacy_boost_records()
    assert not legacy  # None (unset) or empty: nothing valid was moved


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", [], {}, "malformed", -1, True], ids=repr)
async def test_migration_tolerates_malformed_version(bad: Any) -> None:
    config = DictConfig({"global": {"schema_version": bad}})
    await assert_idempotent(migrate_global_schema, config)
    assert await config.schema_version() == GLOBAL_SCHEMA_VERSION
