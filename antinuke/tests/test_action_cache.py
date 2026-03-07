from unittest.mock import patch

from antinuke.utils import ActionCache


class TestActionCache:
    def setup_method(self):
        self.cache = ActionCache()

    @patch("time.time")
    def test_record_action_basic(self, mock_time):
        mock_time.return_value = 100.0

        count = self.cache.record_action(guild_id=1, user_id=2, action_type="test", timeframe=10)
        assert count == 1

        mock_time.return_value = 105.0
        count = self.cache.record_action(guild_id=1, user_id=2, action_type="test", timeframe=10)
        assert count == 2

    @patch("time.time")
    def test_record_action_expiration(self, mock_time):
        mock_time.return_value = 100.0
        self.cache.record_action(guild_id=1, user_id=2, action_type="test", timeframe=10)
        self.cache.record_action(guild_id=1, user_id=2, action_type="test", timeframe=10)

        # Move time forward past the 10-second timeframe
        mock_time.return_value = 115.0
        count = self.cache.record_action(guild_id=1, user_id=2, action_type="test", timeframe=10)

        # The previous 2 actions expired, so only the new one counts
        assert count == 1

    @patch("time.time")
    def test_get_count(self, mock_time):
        mock_time.return_value = 100.0
        self.cache.record_action(guild_id=1, user_id=2, action_type="test", timeframe=10)
        self.cache.record_action(guild_id=1, user_id=2, action_type="test", timeframe=10)

        # Advance time within the timeframe
        mock_time.return_value = 105.0
        assert self.cache.get_count(guild_id=1, user_id=2, action_type="test", timeframe=10) == 2

        # Advance time beyond the timeframe
        mock_time.return_value = 115.0
        assert self.cache.get_count(guild_id=1, user_id=2, action_type="test", timeframe=10) == 0

    @patch("time.time")
    def test_clear_user(self, mock_time):
        mock_time.return_value = 100.0
        self.cache.record_action(guild_id=1, user_id=2, action_type="test", timeframe=10)
        self.cache.record_action(guild_id=1, user_id=3, action_type="test", timeframe=10)

        self.cache.clear_user(guild_id=1, user_id=2)

        assert self.cache.get_count(guild_id=1, user_id=2, action_type="test", timeframe=10) == 0
        assert self.cache.get_count(guild_id=1, user_id=3, action_type="test", timeframe=10) == 1

    @patch("time.time")
    def test_clear_guild(self, mock_time):
        mock_time.return_value = 100.0
        self.cache.record_action(guild_id=1, user_id=2, action_type="test", timeframe=10)
        self.cache.record_action(guild_id=2, user_id=2, action_type="test", timeframe=10)

        self.cache.clear_guild(guild_id=1)

        assert self.cache.get_count(guild_id=1, user_id=2, action_type="test", timeframe=10) == 0
        assert self.cache.get_count(guild_id=2, user_id=2, action_type="test", timeframe=10) == 1

    def test_clear_user_nonexistent(self):
        # Should not raise any exceptions
        self.cache.clear_user(guild_id=999, user_id=999)

    def test_clear_guild_nonexistent(self):
        # Should not raise any exceptions
        self.cache.clear_guild(guild_id=999)
