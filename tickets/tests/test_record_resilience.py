"""Ticket handlers tolerate pending records, isolate auto-close failures, and never strand creations."""

import copy
from datetime import datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from tickets.common.constants import DEFAULT_GUILD, TicketState
from tickets.common.utils import prep_overview_text, prune_invalid_tickets, ticket_channel_id
from tickets.common.views import VerificationModal
from tickets.tickets import Tickets

GUILD_ID = 1
USER_ID = 42


class _Value:
    def __init__(self, state: dict, key: str) -> None:
        self.state = state
        self.key = key

    def __call__(self) -> "_Value":
        return self

    def __await__(self):
        async def read() -> Any:
            return copy.deepcopy(self.state[self.key])

        return read().__await__()

    async def __aenter__(self) -> Any:
        return self.state[self.key]

    async def __aexit__(self, *_: object) -> None:
        return None

    async def set(self, value: Any) -> None:
        self.state[self.key] = value


class _All:
    def __init__(self, state: dict) -> None:
        self.state = state

    def __await__(self):
        async def read() -> dict:
            return copy.deepcopy(self.state)

        return read().__await__()

    async def __aenter__(self) -> dict:
        return self.state

    async def __aexit__(self, *_: object) -> None:
        return None


class _GuildGroup:
    def __init__(self, state: dict) -> None:
        self.state = state

    def all(self) -> _All:
        return _All(self.state)

    def __getattr__(self, key: str) -> _Value:
        return _Value(self.state, key)


class _Config:
    def __init__(self, state: dict) -> None:
        self.state = state

    async def all_guilds(self) -> dict[int, dict]:
        return {GUILD_ID: copy.deepcopy(self.state)}

    def guild(self, _guild: object) -> _GuildGroup:
        return _GuildGroup(self.state)


def _state(**overrides: Any) -> dict:
    state = copy.deepcopy(DEFAULT_GUILD)
    state.update(overrides)
    return state


def _active(opened: datetime | str, **extra: Any) -> dict:
    return {
        "opened": opened if isinstance(opened, str) else opened.isoformat(),
        "pfp": None,
        "logmsg": None,
        "answers": {},
        "has_response": False,
        "message_id": 0,
        "state": TicketState.ACTIVE,
        **extra,
    }


def _pending() -> dict:
    return {
        "opened": datetime.now().astimezone().isoformat(),
        "logmsg": None,
        "channel_id": None,
        "reconcile_token": f"kirin-ticket:{GUILD_ID}:{USER_ID}:9",
        "state": TicketState.PENDING,
    }


async def _no_history(*args: Any, **kwargs: Any):
    for message in ():
        yield message


def _text_channel(channel_id: int) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.name = f"ticket-{channel_id}"
    channel.mention = f"<#{channel_id}>"
    channel.jump_url = f"https://discord.com/channels/{GUILD_ID}/{channel_id}"
    channel.send = AsyncMock()
    channel.history = _no_history
    return channel


def _member(guild: MagicMock) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = USER_ID
    member.name = "user"
    member.display_name = "User"
    member.mention = f"<@{USER_ID}>"
    member.guild = guild
    member.roles = []
    member.avatar = None
    member.display_avatar.url = "https://example.invalid/avatar.png"
    member.color = discord.Color.default()
    member.top_role.name = "Member"
    return member


def _guild(channels: dict[int, MagicMock]) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "Guild"
    guild.member_count = 10
    guild.members = []
    guild.get_channel_or_thread.side_effect = channels.get
    guild.get_channel.side_effect = channels.get
    return guild


def _cog(state: dict, guild: MagicMock) -> Tickets:
    cog = object.__new__(Tickets)
    bot = MagicMock()
    bot.get_guild.side_effect = lambda gid: guild if gid == GUILD_ID else None
    bot.get_valid_prefixes = AsyncMock(return_value=["!"])
    bot.user.name = "Bot"
    cog.bot = bot
    cast(Any, cog).config = _Config(state)
    cog.valid = []
    cog._creation_locks = {}
    cog._num_locks = {}
    cog.view_cache = {GUILD_ID: []}
    return cog


# --- 8.1 key parser ---


@pytest.mark.parametrize(
    ("key", "expected"),
    [("123", 123), (456, 456), ("pending-3", None), ("", None), (None, None), ("-5", None), (True, None)],
)
def test_ticket_channel_id(key: object, expected: int | None) -> None:
    assert ticket_channel_id(key) == expected


# --- 8.2 pending records in every iterating path ---


@pytest.mark.asyncio
async def test_auto_close_skips_pending_and_still_warns_active_ticket() -> None:
    now = datetime.now().astimezone()
    channel = _text_channel(100)
    guild = _guild({100: channel})
    guild.get_member.return_value = _member(guild)
    # Inactive after 1 hour; opened 50 minutes ago, so inside the 20-minute warning window.
    opened = {str(USER_ID): {"pending-9": _pending(), "100": _active(now - timedelta(minutes=50))}}
    cog = _cog(_state(inactive=1, opened=opened), guild)

    await Tickets.auto_close.coro(cog)

    channel.send.assert_awaited_once()
    assert "closed automatically" in channel.send.await_args.args[0]


@pytest.mark.asyncio
async def test_init_guild_skips_pending_records() -> None:
    channel = _text_channel(100)
    guild = _guild({100: channel})
    guild.get_member.return_value = _member(guild)
    opened = {str(USER_ID): {"pending-9": _pending(), "100": _active("2024-01-01T00:00:00+00:00", message_id=555)}}
    state = _state(opened=opened)
    cog = _cog(state, guild)

    with patch("tickets.tickets.CloseView") as close_view:
        await cog._init_guild(guild, copy.deepcopy(state))

    close_view.assert_called_once()
    cast(MagicMock, cog.bot).add_view.assert_called_once()


@pytest.mark.asyncio
async def test_on_member_remove_with_pending_record_closes_active_channels() -> None:
    channel = _text_channel(100)
    guild = _guild({100: channel})
    member = _member(guild)
    opened = {str(USER_ID): {"pending-9": _pending(), "100": _active("2024-01-01T00:00:00+00:00")}}
    cog = _cog(_state(opened=opened), guild)

    with patch("tickets.tickets.close_ticket", new=AsyncMock()) as close:
        await cog.on_member_remove(member)

    close.assert_awaited_once()
    assert close.await_args is not None
    assert close.await_args.kwargs["channel"] is channel


@pytest.mark.asyncio
async def test_prune_keeps_pending_records() -> None:
    guild = _guild({})
    guild.get_member.return_value = _member(guild)
    state = _state(opened={str(USER_ID): {"pending-9": _pending(), "100": _active("2024-01-01T00:00:00+00:00")}})

    pruned = await prune_invalid_tickets(guild, copy.deepcopy(state), cast(Any, _Config(state)))

    assert pruned is True
    assert list(state["opened"][str(USER_ID)]) == ["pending-9"]


def _image_modal(guild: MagicMock, state: dict, created: MagicMock | None) -> tuple[VerificationModal, MagicMock]:
    cog = _cog(state, guild)
    cog.create_ticket_for_user = AsyncMock(return_value=("result", created))  # type: ignore[method-assign]
    modal = object.__new__(VerificationModal)
    modal.bot = MagicMock()
    modal.bot.get_cog.return_value = cog
    modal.guild = guild
    modal.config = cast(Any, _Config(state))
    modal.user = _member(guild)
    modal.image = MagicMock()
    modal.image.values = [MagicMock(url="https://example.invalid/a.png")]
    modal.questions = []
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return modal, interaction


@pytest.mark.asyncio
@pytest.mark.parametrize("created_id", [100, None])
async def test_verification_images_go_to_the_ticket_this_submission_created(created_id: int | None) -> None:
    """An overlapping submission's newer ticket, or a failed creation, must not receive these images."""
    channels = {100: _text_channel(100), 200: _text_channel(200)}
    guild = _guild(channels)
    opened = {
        str(USER_ID): {
            "100": _active("2024-01-01T00:00:00+00:00"),
            "200": _active("2024-01-02T00:00:00+00:00"),
        }
    }
    modal, interaction = _image_modal(guild, _state(opened=opened), channels.get(created_id or 0))

    await modal.on_submit(interaction)

    channels[200].send.assert_not_awaited()
    if created_id:
        channels[100].send.assert_awaited_once()
    else:
        channels[100].send.assert_not_awaited()
    interaction.followup.send.assert_awaited_once_with("result", ephemeral=True)


def test_overview_skips_pending_reservations() -> None:
    channel = _text_channel(100)
    guild = _guild({100: channel})
    guild.get_member.return_value = _member(guild)
    opened = {str(USER_ID): {"pending-9": _pending(), "100": _active("2024-01-01T00:00:00+00:00")}}

    text = prep_overview_text(guild, opened, mention=True)

    assert text == "1. <#100> <t:1704067200:R> - user\n"


# --- 8.3 auto-close isolation ---


@pytest.mark.asyncio
async def test_auto_close_isolates_send_failure_and_malformed_timestamp() -> None:
    now = datetime.now().astimezone()
    failing = _text_channel(100)
    failing.send.side_effect = discord.HTTPException(MagicMock(status=500), "boom")
    malformed = _text_channel(200)
    healthy = _text_channel(300)
    guild = _guild({100: failing, 200: malformed, 300: healthy})
    guild.get_member.return_value = _member(guild)
    warn_window = now - timedelta(minutes=50)
    opened = {
        str(USER_ID): {
            "100": _active(warn_window),
            "200": _active("not-a-timestamp"),
            "300": _active(warn_window),
        }
    }
    cog = _cog(_state(inactive=1, opened=opened), guild)

    await Tickets.auto_close.coro(cog)

    failing.send.assert_awaited_once()
    malformed.send.assert_not_awaited()
    healthy.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_close_isolates_malformed_guild_config() -> None:
    now = datetime.now().astimezone()
    channel = _text_channel(100)
    guild = _guild({100: channel})
    guild.get_member.return_value = _member(guild)
    good = _state(inactive=1, opened={str(USER_ID): {"100": _active(now - timedelta(minutes=50))}})
    cog = _cog(good, guild)
    guilds = {2: {"inactive": 1}, GUILD_ID: good}
    cast(Any, cog).config.all_guilds = AsyncMock(return_value=guilds)
    cast(MagicMock, cog.bot).get_guild.side_effect = lambda gid: guild

    await Tickets.auto_close.coro(cog)

    channel.send.assert_awaited_once()


# --- 8.4 post-creation steps are non-fatal ---


def _creation_setup(log_channel: MagicMock) -> tuple[Tickets, dict, MagicMock, MagicMock]:
    category = MagicMock(spec=discord.CategoryChannel)
    ticket_channel = _text_channel(500)
    ticket_channel.send = AsyncMock(return_value=MagicMock(id=777, jump_url="https://example.invalid/m"))
    category.create_text_channel = AsyncMock(return_value=ticket_channel)
    guild = _guild({20: category, 10: _text_channel(10), 30: log_channel})
    guild.default_role = MagicMock()
    guild.me = MagicMock()
    guild.get_role.return_value = None
    state = _state(category_id=20, channel_id=10, log_channel=30)
    return _cog(state, guild), state, _member(guild), ticket_channel


@pytest.mark.asyncio
async def test_log_send_failure_still_finalizes_ticket() -> None:
    log_channel = _text_channel(30)
    log_channel.send.side_effect = discord.Forbidden(MagicMock(status=403), "missing access")
    cog, state, member, ticket_channel = _creation_setup(log_channel)

    with patch("tickets.common.functions.update_active_overview", new=AsyncMock(return_value=None)):
        result, created = await cog.create_ticket_for_user(member)

    assert ticket_channel.mention in result
    assert created is ticket_channel
    record = state["opened"][str(USER_ID)]
    assert list(record) == ["500"]
    assert record["500"]["state"] == TicketState.ACTIVE
    assert record["500"]["message_id"] == 777
    assert record["500"]["logmsg"] is None


@pytest.mark.asyncio
async def test_welcome_send_failure_still_finalizes_ticket() -> None:
    log_channel = _text_channel(30)
    log_channel.send = AsyncMock(return_value=MagicMock(id=888))
    cog, state, member, ticket_channel = _creation_setup(log_channel)
    ticket_channel.send.side_effect = discord.HTTPException(MagicMock(status=500), "welcome failed")

    with patch("tickets.common.functions.update_active_overview", new=AsyncMock(return_value=None)):
        result, created = await cog.create_ticket_for_user(member)

    assert ticket_channel.mention in result
    assert created is ticket_channel
    record = state["opened"][str(USER_ID)]
    assert list(record) == ["500"]
    assert record["500"]["state"] == TicketState.ACTIVE
    assert record["500"]["message_id"] == 0
    assert record["500"]["logmsg"] == 888


@pytest.mark.asyncio
async def test_auto_close_skips_close_pending_but_retries_close_failed() -> None:
    long_ago = datetime.now().astimezone() - timedelta(hours=5)
    in_flight = _text_channel(100)
    failed = _text_channel(200)
    guild = _guild({100: in_flight, 200: failed})
    guild.get_member.return_value = _member(guild)
    opened = {
        str(USER_ID): {
            "100": _active(long_ago, state=TicketState.CLOSE_PENDING),
            "200": _active(long_ago, state=TicketState.CLOSE_FAILED),
        }
    }
    cog = _cog(_state(inactive=1, opened=opened), guild)

    with patch("tickets.tickets.close_ticket", new=AsyncMock()) as close:
        await Tickets.auto_close.coro(cog)

    close.assert_awaited_once()
    assert close.await_args is not None
    assert close.await_args.args[3] is failed


@pytest.mark.asyncio
async def test_prune_tolerates_a_user_removed_since_the_snapshot() -> None:
    # A departed member's close_ticket can drop their key before the prune writes
    guild = _guild({})
    guild.get_member.return_value = None
    snapshot = _state(opened={str(USER_ID): {"100": _active("2024-01-01T00:00:00+00:00")}})
    state = _state(opened={})

    assert await prune_invalid_tickets(guild, snapshot, cast(Any, _Config(state))) is True
    assert state["opened"] == {}
