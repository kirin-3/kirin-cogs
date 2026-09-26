"""Tests for the RoleLimit cog (merged colourlimit + rolelimit)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rolelimit.rolelimit import RoleLimit, _role_ids, colour_roles_to_remove, ranked_roles_to_remove


def test_role_ids_drops_malformed() -> None:
    assert _role_ids(None) == []
    assert _role_ids({"a": 1}) == []
    assert _role_ids([1, "2", None, True, 3]) == [1, 3]


def test_colour_removes_older_listed_roles_when_listed_role_added() -> None:
    assert colour_roles_to_remove([1, 2, 3], before_ids={1, 9}, added_ids={2}) == {1}


def test_colour_ignores_unlisted_additions() -> None:
    assert colour_roles_to_remove([1, 2, 3], before_ids={1}, added_ids={9}) == set()


def test_ranked_keeps_last_listed_role() -> None:
    assert ranked_roles_to_remove([1, 2, 3, 4], {1, 3, 4, 9}) == {1, 3}
    assert ranked_roles_to_remove([1, 2, 3], {2}) == set()
    assert ranked_roles_to_remove([], {1}) == set()


def _make_cog(colour: list[int], ranked: list[int]) -> RoleLimit:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = RoleLimit(MagicMock())
    cog.bot.cog_disabled_in_guild = AsyncMock(return_value=False)
    cog.colour_config = MagicMock()
    cog.colour_config.guild.return_value.roles = AsyncMock(return_value=colour)
    cog.config = MagicMock()
    cog.config.guild.return_value.roles = AsyncMock(return_value=ranked)
    return cog


def test_config_matches_original_cogs() -> None:
    # The saved settings live under these names; if they drift, the settings are lost.
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = RoleLimit(MagicMock())
    assert (cog.config.cog_name, cog.config.unique_identifier) == ("RoleLimit", "1471894719841")
    assert (cog.colour_config.cog_name, cog.colour_config.unique_identifier) == (
        "ColourLimit",
        "147189471982418789741",
    )


def _member(guild: MagicMock, role_ids: set[int]) -> MagicMock:
    member = MagicMock()
    member.guild = guild
    member.id = 42
    member.roles = [SimpleNamespace(id=i) for i in role_ids]
    member.remove_roles = AsyncMock()
    return member


@pytest.fixture
def guild() -> MagicMock:
    guild = MagicMock()
    guild.id = 1
    guild.me.guild_permissions.manage_roles = True

    def get_role(role_id: int) -> MagicMock:
        role = MagicMock(id=role_id)
        role.is_assignable.return_value = role_id != 99  # 99 sits above the bot
        return role

    guild.get_role.side_effect = get_role
    return guild


def _removed(member: MagicMock) -> set[int]:
    return {r.id for call in member.remove_roles.await_args_list for r in call.args}


@pytest.mark.asyncio
async def test_listener_applies_both_limits(guild: MagicMock) -> None:
    cog = _make_cog(colour=[10, 11, 99], ranked=[20, 21, 22])
    before = _member(guild, {10, 99, 20})
    after = _member(guild, {10, 99, 11, 20, 22})

    await cog.on_member_update(before, after)

    assert _removed(after) == {10, 20}  # 99 is above the bot, so it is skipped


@pytest.mark.asyncio
async def test_listener_ignores_role_removals(guild: MagicMock) -> None:
    cog = _make_cog(colour=[10, 11], ranked=[20, 21])
    before = _member(guild, {10, 11, 20, 21})
    after = _member(guild, {10, 20, 21})

    await cog.on_member_update(before, after)

    after.remove_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_listener_skips_without_manage_roles(guild: MagicMock) -> None:
    guild.me.guild_permissions.manage_roles = False
    cog = _make_cog(colour=[10, 11], ranked=[])
    before = _member(guild, {10})
    after = _member(guild, {10, 11})

    await cog.on_member_update(before, after)

    after.remove_roles.assert_not_awaited()
