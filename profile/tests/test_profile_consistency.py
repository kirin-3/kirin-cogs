"""Consistency, migration-adoption, and malformed-state tests for Profile.

Covers guild/member scope adoption of legacy data (6.3), ``picture_url``
canonicalization (6.4), and concurrency/malformed-state behavior (6.6).
"""

from profile.models import canonicalize_profile_data
from profile.profile import Profile
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from testutils.migration import DictConfig

GUILD_ID = 4321


def _make_cog(config: DictConfig) -> Profile:
    cog = Profile.__new__(Profile)
    cog.config = config  # type: ignore[assignment]
    return cog


def _guild(guild_id: int = GUILD_ID) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    return guild


LEGACY_USER_DATA: dict[str, Any] = {
    "profile_data": {"name": "Alice", "age": 28, "picture": "https://example.com/legacy.png"},
    "message_id": 9001,
    "last_delete": 1_700_000_000.0,
}


def _legacy_config() -> DictConfig:
    return DictConfig(
        {
            "global": {"channel_id": 555, "sticky_message_id": 777, "cooldown": 9},
            "user": {42: dict(LEGACY_USER_DATA)},
        }
    )


# ---------------------------------------------------------------------------
# 6.4 canonicalize_profile_data
# ---------------------------------------------------------------------------


def test_canonicalize_maps_legacy_picture() -> None:
    result = canonicalize_profile_data({"name": "A", "picture": "https://x/img.png"})
    assert result.get("picture_url") == "https://x/img.png"
    assert "picture" not in result


def test_canonicalize_prefers_existing_canonical() -> None:
    result = canonicalize_profile_data({"picture": "https://x/old.png", "picture_url": "https://x/new.png"})
    assert result.get("picture_url") == "https://x/new.png"


def test_canonicalize_ignores_malformed_legacy_picture() -> None:
    assert canonicalize_profile_data({"picture": 123}) == {}
    assert canonicalize_profile_data({"picture": ""}) == {}
    assert canonicalize_profile_data({"picture": None}) == {}
    assert canonicalize_profile_data({}) == {}


# ---------------------------------------------------------------------------
# 6.3 lazy per-guild adoption
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adoption_copies_legacy_config_and_profiles() -> None:
    config = _legacy_config()
    cog = _make_cog(config)

    await cog._ensure_guild_data(_guild())

    guild_group = config.guild_from_id(GUILD_ID).raw()
    assert guild_group["channel_id"] == 555
    assert guild_group["sticky_message_id"] == 777
    assert guild_group["cooldown"] == 9
    assert guild_group["legacy_adopted"] is True

    member = config.member_from_ids(GUILD_ID, 42).raw()
    assert member["profile_data"]["name"] == "Alice"
    # Legacy `picture` was canonicalized to `picture_url`
    assert member["profile_data"]["picture_url"] == "https://example.com/legacy.png"
    assert "picture" not in member["profile_data"]
    assert member["message_id"] == 9001
    assert member["last_delete"] == LEGACY_USER_DATA["last_delete"]

    # Rollback-safe: legacy sources are left untouched
    assert config.user_from_id(42).raw() == LEGACY_USER_DATA
    snapshot_global = config.snapshot()["global"]
    assert snapshot_global["channel_id"] == 555


@pytest.mark.asyncio
async def test_adoption_is_idempotent() -> None:
    config = _legacy_config()
    cog = _make_cog(config)

    await cog._ensure_guild_data(_guild())
    first = config.snapshot()
    await cog._ensure_guild_data(_guild())
    assert config.snapshot() == first


@pytest.mark.asyncio
async def test_adoption_does_not_overwrite_guild_config() -> None:
    config = _legacy_config()
    config.guild_from_id(GUILD_ID).raw()["channel_id"] = 999
    cog = _make_cog(config)

    await cog._ensure_guild_data(_guild())

    assert config.guild_from_id(GUILD_ID).raw()["channel_id"] == 999


@pytest.mark.asyncio
async def test_adoption_two_guilds_are_independent() -> None:
    """Two guilds adopt legacy data independently (spec: consistent scoping)."""
    config = _legacy_config()
    cog = _make_cog(config)

    await cog._ensure_guild_data(_guild(1111))
    await cog._ensure_guild_data(_guild(2222))

    for gid in (1111, 2222):
        assert config.guild_from_id(gid).raw()["channel_id"] == 555
        assert config.member_from_ids(gid, 42).raw()["profile_data"]["name"] == "Alice"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_data",
    [None, {}, "junk", {"profile_data": None}, {"profile_data": []}, {"profile_data": "nope"}],
    ids=repr,
)
async def test_adoption_tolerates_malformed_legacy_user_data(user_data: Any) -> None:
    config = DictConfig({"user": {7: user_data}})
    cog = _make_cog(config)

    await cog._ensure_guild_data(_guild())

    assert config.guild_from_id(GUILD_ID).raw()["legacy_adopted"] is True


@pytest.mark.asyncio
async def test_adoption_concurrent_calls_stay_consistent() -> None:
    """Concurrent first-use adoption converges to one canonical copy."""
    import asyncio

    config = _legacy_config()
    cog = _make_cog(config)
    guild = _guild()

    await asyncio.gather(*(cog._ensure_guild_data(guild) for _ in range(5)))

    guild_group = config.guild_from_id(GUILD_ID).raw()
    assert guild_group["legacy_adopted"] is True
    member = config.member_from_ids(GUILD_ID, 42).raw()
    assert member["profile_data"]["picture_url"] == "https://example.com/legacy.png"


# ---------------------------------------------------------------------------
# 6.4 builder reads legacy `picture` as `picture_url`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_create_edit_canonicalizes_legacy_picture() -> None:
    """A legacy profile containing `picture` is displayed via `picture_url`."""
    from profile.tests.test_profile import (
        _make_interaction,
        _make_member,
        _make_profile_config_mock,
    )

    config_mock = _make_profile_config_mock()
    config_mock.member.return_value.all = AsyncMock(
        return_value={
            "profile_data": {"name": "Alice", "picture": "https://example.com/legacy.png"},
            "message_id": None,
            "last_delete": None,
        }
    )

    bot_mock = MagicMock()
    bot_mock.is_owner = AsyncMock(return_value=False)
    bot_mock.add_view = MagicMock()

    from unittest.mock import patch

    with patch("profile.profile.Config.get_conf", return_value=config_mock):
        cog = Profile(bot_mock)
    cog.config = config_mock

    member = _make_member()
    interaction = _make_interaction(member, guild=_guild())

    captured: dict[str, Any] = {}
    fake_view = MagicMock()
    fake_view.wait = AsyncMock()
    fake_view.submitted = False

    def _capture(user: object, data: dict) -> MagicMock:
        captured["data"] = data
        return fake_view

    with patch("profile.profile.ProfileBuilderView", side_effect=_capture):
        await cog.handle_create_edit(interaction)

    assert captured["data"]["picture_url"] == "https://example.com/legacy.png"
    assert "picture" not in captured["data"]
