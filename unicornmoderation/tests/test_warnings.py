"""Unit tests for warning accumulation via Config mock."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redbot.core import Config

from unicornmoderation.unicorn_moderation import UnicornModeration

LOG_CHANNEL_ID = 694857480307474432


@pytest.fixture
def cog_with_warnings() -> tuple[UnicornModeration, MagicMock]:
    """Cog with a config mock that tracks warning appends."""
    config = MagicMock(spec=Config)
    stored_warnings: list[dict] = []

    class _WarningsContext:
        async def __aenter__(self) -> list[dict]:
            return stored_warnings

        async def __aexit__(self, *args: object) -> None:
            pass

    def _member(*args: object, **kwargs: object) -> object:
        class _Group:
            def warnings(self) -> _WarningsContext:  # type: ignore[override]
                return _WarningsContext()

        return _Group()

    config.member.side_effect = _member

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    bot.loop.run_in_executor = AsyncMock()

    with patch("unicornmoderation.unicorn_moderation.Config.get_conf", return_value=config):
        cog = UnicornModeration(bot)  # type: ignore[arg-type]
    cog.config = config

    return cog, config


@pytest.mark.asyncio
async def test_warn_accumulates_warnings(cog_with_warnings: tuple[UnicornModeration, MagicMock]) -> None:
    """warn command accumulates warnings in Config."""
    cog, config = cog_with_warnings

    stored_warnings: list[dict] = []

    class _WarningsContext:
        async def __aenter__(self) -> list[dict]:
            return stored_warnings

        async def __aexit__(self, *args: object) -> None:
            pass

    def _member(*args: object, **kwargs: object) -> object:
        class _Group:
            def warnings(self) -> _WarningsContext:  # type: ignore[override]
                return _WarningsContext()

        return _Group()

    config.member.side_effect = _member

    member = MagicMock()
    member.display_name = "TestUser"
    member.mention = "@TestUser"

    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.author = MagicMock()
    ctx.author.id = 999
    ctx.message = MagicMock()
    ctx.message.created_at.isoformat = MagicMock(return_value="2024-01-01T00:00:00+00:00")
    ctx.send = AsyncMock()

    await cog.warn.callback(cog, ctx, member, reason="First warning")  # type: ignore[attr-defined]
    await cog.warn.callback(cog, ctx, member, reason="Second warning")  # type: ignore[attr-defined]

    assert len(stored_warnings) == 2
    assert stored_warnings[0]["reason"] == "First warning"
    assert stored_warnings[1]["reason"] == "Second warning"


@pytest.mark.asyncio
async def test_warn_calls_log_action(cog_with_warnings: tuple[UnicornModeration, MagicMock]) -> None:
    """warn command calls _log_action."""
    cog, _ = cog_with_warnings

    member = MagicMock()
    member.display_name = "WarnUser"
    member.mention = "@WarnUser"

    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.author = MagicMock()
    ctx.message = MagicMock()
    ctx.message.created_at.isoformat = MagicMock(return_value="2024-01-01T00:00:00+00:00")
    ctx.send = AsyncMock()

    log_action_called = []
    original = cog._log_action

    async def capture_log(action: str, m: object, reason: str) -> None:
        log_action_called.append((action, reason))

    cog._log_action = capture_log  # type: ignore[method-assign]

    await cog.warn.callback(cog, ctx, member, reason="test reason")  # type: ignore[attr-defined]

    assert len(log_action_called) == 1
    assert log_action_called[0][0] == "Warning"
    assert log_action_called[0][1] == "test reason"

    cog._log_action = original  # type: ignore[method-assign]
