# Mock discord and other potential missing modules
from unittest.mock import MagicMock

from antinuke.utils import (
    has_dangerous_permission,
    is_above_in_hierarchy,
)


def test_has_dangerous_permission():
    # Setup mocks
    before = MagicMock()
    after = MagicMock()

    # Configure so that "administrator" was added
    before.administrator = False
    after.administrator = True

    # "manage_guild" wasn't changed
    before.manage_guild = False
    after.manage_guild = False

    # "ban_members" was removed
    before.ban_members = True
    after.ban_members = False

    dangerous_perms = ["administrator", "manage_guild", "ban_members"]

    # Should detect "administrator" was added
    assert has_dangerous_permission(before, after, dangerous_perms) == "administrator"


def test_has_dangerous_permission_none_added():
    before = MagicMock()
    after = MagicMock()

    before.administrator = True
    after.administrator = True

    before.manage_guild = False
    after.manage_guild = False

    dangerous_perms = ["administrator", "manage_guild"]

    assert has_dangerous_permission(before, after, dangerous_perms) is None


def test_has_dangerous_permission_missing_attr():
    before = MagicMock()
    after = MagicMock()

    # simulate some custom permission that doesn't exist on the object
    del after.not_a_real_perm

    dangerous_perms = ["not_a_real_perm", "administrator"]

    before.administrator = False
    after.administrator = True

    # It should skip "not_a_real_perm" and find "administrator"
    assert has_dangerous_permission(before, after, dangerous_perms) == "administrator"


def test_is_above_in_hierarchy():
    bot_member = MagicMock()
    target = MagicMock()

    bot_member.top_role = 10
    target.top_role = 5

    assert is_above_in_hierarchy(bot_member, target) is True

    bot_member.top_role = 5
    target.top_role = 10

    assert is_above_in_hierarchy(bot_member, target) is False

    bot_member.top_role = 5
    target.top_role = 5

    assert is_above_in_hierarchy(bot_member, target) is False
