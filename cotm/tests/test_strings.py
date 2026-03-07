"""Unit tests for cotm.unicornia.strings"""

import pytest
from cotm.unicornia import strings

def test_replace_pronouns():
    assert strings.replace_pronouns("i like this") == "you like this"
    assert strings.replace_pronouns("this is mine") == "this is yours"
    assert strings.replace_pronouns("we are our best") == "you all are your best"
    assert strings.replace_pronouns("hello, me!") == "hello, you!"
    # Ensure commas/punctuation handled properly but space remains
    assert strings.replace_pronouns("me, i, mine") == "you, you, yours"
    assert strings.replace_pronouns("my house") == "your house"
    assert strings.replace_pronouns("give it to us") == "give it to you all"
    # Case sensitivity (Capitalization)
    assert strings.replace_pronouns("I like this") == "You like this"
    assert strings.replace_pronouns("Mine is here") == "Yours is here"
    # Multiple punctuations
    assert strings.replace_pronouns("Is it me???") == "Is it you???"

def test_get_indefinite_article():
    assert strings.get_indefinite_article("apple") == "an"
    assert strings.get_indefinite_article("banana") == "a"
    assert strings.get_indefinite_article("hour") == "an"
    assert strings.get_indefinite_article("honest") == "an"
    assert strings.get_indefinite_article("heir") == "an"
    assert strings.get_indefinite_article("honor") == "an"
    assert strings.get_indefinite_article("University") == "an"  # Based on code logic, starts with 'u' (vowel) -> 'an'

def test_pluralize():
    assert strings.pluralize("child") == "children"
    assert strings.pluralize("man") == "men"
    assert strings.pluralize("woman") == "women"
    assert strings.pluralize("cat") == "cats"
    assert strings.pluralize("dog") == "dogs"
    assert strings.pluralize("city") == "cities"
    assert strings.pluralize("boy") == "boys"  # 'y' preceded by vowel
    assert strings.pluralize("bus") == "buses"
    assert strings.pluralize("ash") == "ashes"
    assert strings.pluralize("church") == "churches"
    assert strings.pluralize("box") == "boxes"
    assert strings.pluralize("buzz") == "buzzes"
    assert strings.pluralize("leaf") == "leaves"
    assert strings.pluralize("knife") == "knives"

def test_format_string():
    assert strings.format_string("Hello {name}", name="World") == "Hello World"
    assert strings.format_string("No placeholders here", name="World") == "No placeholders here"
    assert strings.format_string("{a} and {b}", a=1, b=2) == "1 and 2"

def test_remove_emojis():
    assert strings.remove_emojis("Hello 😀") == "Hello "
    assert strings.remove_emojis("🚀 Launch") == " Launch"
    assert strings.remove_emojis("No emojis here") == "No emojis here"

def test_dict_to_string():
    d = {"a": 1, "b": 2}
    assert strings.dict_to_string(d) == "a: 1\nb: 2"
    assert strings.dict_to_string({}) == ""

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
