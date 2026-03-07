"""Unit tests for can_close and get_ticket_owner utility functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redbot.core.bot import Red

from tickets.common.utils import can_close, get_ticket_owner

# --- get_ticket_owner ---


def test_get_ticket_owner_returns_correct_uid() -> None:
    """Returns owner UID when ticket channel exists in their ticket set."""
    opened = {
        "111": {"chan_100": {}, "chan_200": {}},
        "222": {"chan_300": {}},
    }
    result = get_ticket_owner(opened, "chan_300")
    assert result == "222"


def test_get_ticket_owner_returns_none_when_not_found() -> None:
    """Returns None when ticket channel does not belong to any user."""
    opened = {"111": {"chan_100": {}}}
    result = get_ticket_owner(opened, "chan_999")
    assert result is None


def test_get_ticket_owner_empty_opened() -> None:
    """Empty opened dict returns None safely."""
    result = get_ticket_owner({}, "chan_1")
    assert result is None


# --- can_close ---


def make_conf(
    owner_id: str = "111",
    channel_id: str = "chan_100",
    support_role_ids: list[int] | None = None,
    user_can_close: bool = False,
) -> dict:
    return {
        "opened": {
            owner_id: {channel_id: {"pfp": "", "logmsg": None, "opened": "2024-01-01T00:00:00"}},
        },
        "support_roles": [[r] for r in (support_role_ids or [])],
        "user_can_close": user_can_close,
    }


@pytest.mark.asyncio
async def test_can_close_guild_owner_can_close() -> None:
    """Guild owner should always be able to close tickets."""
    bot = MagicMock(spec=Red)

    guild = MagicMock()
    guild.owner_id = 999

    channel = MagicMock()
    channel.id = 100

    author = MagicMock()
    author.id = 999  # guild owner
    author.roles = []

    conf = make_conf(owner_id="111", channel_id="100")

    with patch("tickets.common.utils.is_admin_or_superior", new_callable=AsyncMock, return_value=False):
        result = await can_close(bot, guild, channel, author, "111", conf)  # type: ignore[arg-type]

    assert result is True


@pytest.mark.asyncio
async def test_can_close_owner_can_close_when_permitted() -> None:
    """Ticket owner can close their own ticket when user_can_close is True."""
    bot = MagicMock(spec=Red)

    guild = MagicMock()
    guild.owner_id = 999

    channel = MagicMock()
    channel.id = 100

    author = MagicMock()
    author.id = 111
    author.roles = []

    conf = make_conf(owner_id="111", channel_id="100", user_can_close=True)

    with patch("tickets.common.utils.is_admin_or_superior", new_callable=AsyncMock, return_value=False):
        result = await can_close(bot, guild, channel, author, 111, conf)  # type: ignore[arg-type]

    assert result is True


@pytest.mark.asyncio
async def test_can_close_non_owner_non_support_cannot_close() -> None:
    """Regular member who is not owner/support cannot close a ticket they don't own."""
    bot = MagicMock(spec=Red)

    guild = MagicMock()
    guild.owner_id = 999

    channel = MagicMock()
    channel.id = 100

    author = MagicMock()
    author.id = 555
    author.roles = []

    conf = make_conf(owner_id="111", channel_id="100", user_can_close=False)

    with patch("tickets.common.utils.is_admin_or_superior", new_callable=AsyncMock, return_value=False):
        result = await can_close(bot, guild, channel, author, "111", conf)  # type: ignore[arg-type]

    assert result is False


@pytest.mark.asyncio
async def test_can_close_returns_false_if_channel_not_in_opened() -> None:
    """Returns False when channel ID is not in the opened tickets dict."""
    bot = MagicMock(spec=Red)

    guild = MagicMock()
    channel = MagicMock()
    channel.id = 999  # Not in conf

    author = MagicMock()
    author.id = 111
    author.roles = []

    conf = make_conf(owner_id="111", channel_id="100")

    with patch("tickets.common.utils.is_admin_or_superior", new_callable=AsyncMock, return_value=False):
        result = await can_close(bot, guild, channel, author, "111", conf)  # type: ignore[arg-type]

    assert result is False
