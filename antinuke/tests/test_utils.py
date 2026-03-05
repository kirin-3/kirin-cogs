# Mock discord and other potential missing modules
import sys
from unittest.mock import MagicMock

class MockCog:
    pass

class MockType(type):
    pass

discord = MagicMock()
sys.modules["discord"] = discord
sys.modules["discord.ext"] = MagicMock()
sys.modules["discord.ext.commands"] = MagicMock()

redbot = MagicMock()
sys.modules["redbot"] = redbot
redbot_core = MagicMock()
sys.modules["redbot.core"] = redbot_core
redbot_core.commands = MagicMock()
redbot_core.commands.Cog = MockCog
sys.modules["redbot.core.bot"] = MagicMock()
sys.modules["redbot.core.utils"] = MagicMock()
sys.modules["redbot.core.utils.chat_formatting"] = MagicMock()

# Instead of importing AntiNuke, which has problematic imports and metaclass definitions
# for a simple utility test, we'll try to directly import from utils if possible.
# But antinuke/__init__.py imports AntiNuke.
# So we must satisfy AntiNuke's requirements or mock the whole module.

# Let's try to mock the metaclass problematic part
sys.modules["antinuke.antinuke"] = MagicMock()

from antinuke.utils import format_permission_name

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
