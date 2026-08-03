"""Rollback-safe migration fixtures and version-marker tests for Tickets."""

from typing import Any

import pytest

from testutils.migration import DictConfig, assert_idempotent, historical_variants
from tickets.common.constants import DEFAULT_GUILD
from tickets.migrations import GUILD_SCHEMA_VERSION, migrate_guild_schemas

# Representative pre-migration (v0) guild record: everything Tickets stored
# before schema version markers existed.
LEGACY_GUILD_RECORD: dict[str, Any] = {
    "support_roles": [11, 12],
    "blacklist": [13],
    "max_tickets": 2,
    "inactive": 24,
    "overview_channel": 100,
    "overview_msg": 101,
    "dm": True,
    "user_can_close": True,
    "category_id": 200,
    "channel_id": 201,
    "message_id": 202,
    "button_text": "Open a Ticket",
    "ticket_num": 42,
    "log_channel": 300,
    "opened": {
        "99": {
            "555": {
                "opened": "2024-01-01T00:00:00",
                "pfp": None,
                "logmsg": None,
                "answers": {"Issue": "Help"},
                "has_response": False,
                "message_id": 777,
                "overview_msg": None,
            }
        }
    },
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
    historical_variants(DEFAULT_GUILD, scope="guild", record_id=99),
    ids=lambda s: repr(s)[:60],
)
async def test_migration_tolerates_malformed_history(snapshot: dict[str, Any]) -> None:
    await assert_idempotent(migrate_guild_schemas, DictConfig(snapshot))
