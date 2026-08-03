"""Tests for the reusable Config-migration test machinery.

A representative migration (version marker bump plus a legacy field rename,
mirroring the per-cog migrations in this change) is exercised against missing,
``None``, empty, and malformed historical values.
"""

from typing import Any

import pytest

from testutils.migration import (
    DictConfig,
    assert_idempotent,
    historical_variants,
)

EXAMPLE_DEFAULTS = {
    "version": 0,
    "picture_url": None,
    "nickname": "",
}


async def example_migration(config: DictConfig) -> None:
    """Representative migration: rename legacy ``picture`` to ``picture_url``.

    - Reads tolerate missing, ``None``, empty, and wrong-typed values.
    - Unrecoverable legacy values are preserved (never dropped silently).
    - The ``version`` marker makes repeat runs no-ops.
    """
    for guild_id in await config.all_guilds():
        group = config.guild_from_id(guild_id)
        data = group.raw()

        version = data.get("version")
        if not isinstance(version, int) or isinstance(version, bool):
            version = 0
        if version >= 1:
            continue

        legacy = data.get("picture")
        current = data.get("picture_url")
        if isinstance(legacy, str) and legacy and not isinstance(current, str):
            data["picture_url"] = legacy
        if isinstance(current, str) or isinstance(legacy, str):
            data.pop("picture", None)

        nickname = data.get("nickname")
        if nickname is not None and not isinstance(nickname, str):
            data["nickname"] = ""

        data["version"] = 1


# ---------------------------------------------------------------------------
# DictConfig double behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dict_value_roundtrip() -> None:
    config = DictConfig({"guild": {7: {"name": "abc"}}})
    group = config.guild_from_id(7)
    assert await group.name() == "abc"
    await group.name.set("def")
    assert await group.name() == "def"


@pytest.mark.asyncio
async def test_dict_value_returns_copies() -> None:
    config = DictConfig({"guild": {7: {"items": [1]}}})
    group = config.guild_from_id(7)
    value = await group.items()
    value.append(2)
    assert await group.items() == [1]


@pytest.mark.asyncio
async def test_group_context_manager_mutates_raw() -> None:
    config = DictConfig({"guild": {7: {}}})
    async with config.guild_from_id(7)() as data:
        data["x"] = 1
    assert config.guild_from_id(7).raw() == {"x": 1}


@pytest.mark.asyncio
async def test_scoped_groups_and_bulk_reads() -> None:
    config = DictConfig(
        {
            "global": {"g": 1},
            "guild": {1: {"a": 1}},
            "user": {2: {"b": 2}},
            "member": {1: {2: {"c": 3}}},
        }
    )
    assert await config.all() == {"g": 1}
    assert await config.all_guilds() == {1: {"a": 1}}
    assert await config.all_users() == {2: {"b": 2}}
    assert await config.all_members() == {1: {2: {"c": 3}}}


@pytest.mark.asyncio
async def test_member_group_by_object() -> None:
    class FakeGuild:
        id = 5

    class FakeMember:
        id = 9
        guild = FakeGuild()

    config = DictConfig({"member": {5: {9: {"v": True}}}})
    assert await config.member(FakeMember()).v() is True


# ---------------------------------------------------------------------------
# Idempotency contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_example_migration_renames_legacy_and_marks_version() -> None:
    config = DictConfig({"guild": {3: {"picture": "http://x/img.png"}}})
    await example_migration(config)
    data = config.guild_from_id(3).raw()
    assert data["picture_url"] == "http://x/img.png"
    assert "picture" not in data
    assert data["version"] == 1


@pytest.mark.asyncio
async def test_example_migration_is_idempotent() -> None:
    config = DictConfig({"guild": {3: {"picture": "http://x/img.png", "nickname": "n"}}})
    await assert_idempotent(example_migration, config)


@pytest.mark.asyncio
async def test_example_migration_preserves_canonical_field() -> None:
    config = DictConfig({"guild": {3: {"picture": "http://x/old.png", "picture_url": "http://x/new.png"}}})
    await example_migration(config)
    assert config.guild_from_id(3).raw()["picture_url"] == "http://x/new.png"


@pytest.mark.asyncio
async def test_assert_idempotent_detects_unstable_migration() -> None:
    async def bad_migration(config: DictConfig) -> None:
        for guild_id in await config.all_guilds():
            group = config.guild_from_id(guild_id)
            data = group.raw()
            data["counter"] = int(data.get("counter") or 0) + 1

    config = DictConfig({"guild": {1: {}}})
    with pytest.raises(AssertionError, match="not idempotent"):
        await assert_idempotent(bad_migration, config)


# ---------------------------------------------------------------------------
# Malformed historical data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "snapshot",
    historical_variants(EXAMPLE_DEFAULTS, scope="guild", record_id=42),
    ids=lambda s: repr(s)[:60],
)
async def test_example_migration_tolerates_historical_variants(snapshot: dict[str, Any]) -> None:
    """Every hostile historical shape migrates without error and stays stable."""
    config = DictConfig(snapshot)
    await assert_idempotent(example_migration, config)
    if snapshot.get("guild", {}).get(42) is not None:
        # A record that existed before migration must carry the version marker.
        assert config.guild_from_id(42).raw().get("version") == 1


@pytest.mark.asyncio
async def test_historical_variants_cover_missing_none_empty_malformed() -> None:
    variants = historical_variants({"a": 1, "b": 2}, scope="guild", record_id=1)
    assert {} in variants  # record absent
    assert {"guild": {1: {}}} in variants  # record empty
    for key in ("a", "b"):
        assert {"guild": {1: {key: None}}} in variants
        assert {"guild": {1: {key: ""}}} in variants
        assert {"guild": {1: {key: []}}} in variants
        assert {"guild": {1: {key: {}}}} in variants
        assert {"guild": {1: {key: "malformed"}}} in variants
