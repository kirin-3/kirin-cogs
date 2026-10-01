"""Unit tests for cotm.unicornia.strings"""

from cotm.unicornia import strings


def test_format_string():
    assert strings.format_string("Hello {name}", name="World") == "Hello World"
    assert strings.format_string("No placeholders here", name="World") == "No placeholders here"
    assert strings.format_string("{a} and {b}", a=1, b=2) == "1 and 2"


def test_add_ordinal_suffix():
    assert strings.add_ordinal_suffix(1) == "1st"
    assert strings.add_ordinal_suffix(2) == "2nd"
    assert strings.add_ordinal_suffix(3) == "3rd"
    assert strings.add_ordinal_suffix(4) == "4th"
    assert strings.add_ordinal_suffix(11) == "11th"
    assert strings.add_ordinal_suffix(12) == "12th"
    assert strings.add_ordinal_suffix(13) == "13th"
    assert strings.add_ordinal_suffix(21) == "21st"
    assert strings.add_ordinal_suffix(22) == "22nd"
    assert strings.add_ordinal_suffix(23) == "23rd"
    assert strings.add_ordinal_suffix(100) == "100th"
    assert strings.add_ordinal_suffix(101) == "101st"
