"""Tests for the Mjolnir cog."""

from unittest.mock import MagicMock, patch

from mjolnir.mjolnir import Mjolnir, leaderboard_lines


def test_config_matches_original_cog() -> None:
    with patch("redbot.core.config.get_driver", return_value=MagicMock()):
        cog = Mjolnir(MagicMock())
    assert (cog.config.cog_name, cog.config.unique_identifier) == ("Mjolnir", "1242351245243535476356")


def test_leaderboard_ranks_and_skips_bad_entries() -> None:
    users = {1: {"lifted": 3}, 2: {"lifted": 85}, 3: {"lifted": 0}, 4: {}, 5: "junk", 6: {"lifted": "7"}}
    assert leaderboard_lines(users, lambda uid: f"u{uid}") == ["1. **u2:** 85", "2. **u1:** 3"]
