# Mock discord and other potential missing modules
from unittest.mock import MagicMock

from antinuke.utils import (
    format_permission_name,
    has_dangerous_permission,
    is_above_in_hierarchy,
)


def test_format_permission_name_single_word():
    assert format_permission_name("administrator") == "Administrator"


def test_format_permission_name_multiple_words():
    assert format_permission_name("manage_guild") == "Manage Guild"
    assert format_permission_name("view_audit_log") == "View Audit Log"


def test_format_permission_name_already_formatted():
    assert format_permission_name("Manage Roles") == "Manage Roles"


def test_format_permission_name_mixed_case():
    assert format_permission_name("MANAGE_WEBHOOKS") == "Manage Webhooks"


def test_format_permission_name_empty_string():
    assert format_permission_name("") == ""


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


from unittest.mock import patch

import antinuke.utils


def test_get_permission_diff():
    # We need to mock discord.Permissions.VALID_FLAGS
    class MockPermissions:
        VALID_FLAGS = {
            "administrator": 8,
            "manage_guild": 32,
            "ban_members": 4,
            "kick_members": 2,
        }

    with patch("antinuke.utils.discord.Permissions", MockPermissions):
        before = MagicMock()
        after = MagicMock()

        # Added
        setattr(before, "administrator", False)
        setattr(after, "administrator", True)

        setattr(before, "manage_guild", False)
        setattr(after, "manage_guild", True)

        # Removed
        setattr(before, "ban_members", True)
        setattr(after, "ban_members", False)

        # Unchanged
        setattr(before, "kick_members", True)
        setattr(after, "kick_members", True)

        diff = antinuke.utils.get_permission_diff(before, after)

        # Both orderless check
        assert len(diff) == 2
        assert "administrator" in diff
        assert "manage_guild" in diff


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
