"""dpytest integration tests for unicornmoderation commands."""

from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unicornmoderation.unicorn_moderation import UnicornModeration

LOG_CHANNEL_ID = 694857480307474432
MUTED_ROLE_ID = 686252873583165520


def make_cog() -> UnicornModeration:
    config_mock = MagicMock()
    config_mock.member.return_value = MagicMock()

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    bot.loop.run_in_executor = AsyncMock()

    with patch("unicornmoderation.unicorn_moderation.Config.get_conf", return_value=config_mock):
        cog = UnicornModeration(bot)  # type: ignore[arg-type]
    cog.config = config_mock
    return cog


def make_ctx(guild: MagicMock | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.guild = guild or MagicMock()
    ctx.author = MagicMock()
    ctx.author.name = "Moderator"
    ctx.send = AsyncMock()
    return ctx


def make_member() -> MagicMock:
    m = MagicMock()
    m.display_name = "Target"
    m.mention = "@Target"
    m.ban = AsyncMock()
    m.kick = AsyncMock()
    m.add_roles = AsyncMock()
    m.remove_roles = AsyncMock()
    return m


# --- ban ---


@pytest.mark.asyncio
async def test_ban_calls_member_ban_and_logs() -> None:
    cog = make_cog()
    ctx = make_ctx()
    member = make_member()

    cog._log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.ban.callback(cog, ctx, member, reason="spam")  # type: ignore[attr-defined]

    member.ban.assert_called_once()
    cog._log_action.assert_called_once()
    ctx.send.assert_called_once()
    assert "Banned" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_ban_default_reason() -> None:
    cog = make_cog()
    ctx = make_ctx()
    member = make_member()
    cog._log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.ban.callback(cog, ctx, member, reason=None)  # type: ignore[attr-defined]

    member.ban.assert_called_once()
    call_kwargs = member.ban.call_args[1]
    assert "Banned by" in call_kwargs["reason"]


# --- kick ---


@pytest.mark.asyncio
async def test_kick_calls_member_kick_and_logs() -> None:
    cog = make_cog()
    ctx = make_ctx()
    member = make_member()
    cog._log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.kick.callback(cog, ctx, member, reason="disruptive")  # type: ignore[attr-defined]

    member.kick.assert_called_once()
    cog._log_action.assert_called_once()
    ctx.send.assert_called_once()
    assert "Kicked" in ctx.send.call_args[0][0]


# --- mute: missing role error path ---


@pytest.mark.asyncio
async def test_mute_missing_role_sends_error() -> None:
    cog = make_cog()
    ctx = make_ctx()
    member = make_member()

    ctx.guild.get_role = MagicMock(return_value=None)
    cog._log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.mute.callback(cog, ctx, member, reason="loud")  # type: ignore[attr-defined]

    member.add_roles.assert_not_called()
    ctx.send.assert_called_once()
    assert "could not be found" in ctx.send.call_args[0][0]


# --- mute: success path ---


@pytest.mark.asyncio
async def test_mute_adds_role_and_logs() -> None:
    cog = make_cog()
    ctx = make_ctx()
    member = make_member()

    mock_role = MagicMock()
    ctx.guild.get_role = MagicMock(return_value=mock_role)
    cog._log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.mute.callback(cog, ctx, member, reason="noisy")  # type: ignore[attr-defined]

    member.add_roles.assert_called_once_with(mock_role, reason="noisy")
    cog._log_action.assert_called_once()
    ctx.send.assert_called_once()
    assert "Muted" in ctx.send.call_args[0][0]


# --- unmute ---


@pytest.mark.asyncio
async def test_unmute_removes_role_and_logs() -> None:
    cog = make_cog()
    ctx = make_ctx()
    member = make_member()

    mock_role = MagicMock()
    ctx.guild.get_role = MagicMock(return_value=mock_role)
    cog._log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.unmute.callback(cog, ctx, member, reason=None)  # type: ignore[attr-defined]

    member.remove_roles.assert_called_once()
    cog._log_action.assert_called_once()
    ctx.send.assert_called_once()
    assert "Unmuted" in ctx.send.call_args[0][0]


# --- warn ---


@pytest.mark.asyncio
async def test_warn_sends_confirmation_and_logs() -> None:
    cog = make_cog()
    ctx = make_ctx()
    member = make_member()
    ctx.message = MagicMock()
    ctx.message.created_at.isoformat = MagicMock(return_value="2024-01-01T00:00:00+00:00")

    cog._log_action = AsyncMock()  # type: ignore[method-assign]

    # warnings() is used as async context manager
    warnings_list: list[dict] = []

    class _Warning:
        async def __aenter__(self) -> list[dict]:
            return warnings_list

        async def __aexit__(self, *args: object) -> None:
            pass

    cast(MagicMock, cog.config.member.return_value).warnings = _Warning  # type: ignore[assignment]

    await cog.warn.callback(cog, ctx, member, reason="test warn")  # type: ignore[attr-defined]

    cog._log_action.assert_called_once()
    ctx.send.assert_called_once()
    assert "Warned" in ctx.send.call_args[0][0]
