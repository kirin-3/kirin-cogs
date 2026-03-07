"""Tests for the Patron cog.

Unit tests cover:
- parse_amount: currency string parsing edge cases
- calculate_reward: tier/bonus calculation
- _process_sheet_logic: role assignment, currency awarding, dedup, annual tracking
- award_currency: Unicornia integration
- process_sheet: lock guard

dpytest integration tests cover:
- patronset setup / roles / logchannel / sync commands via bot dispatch
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config

from patron.patron import Patron

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_guild_config(overrides: dict | None = None) -> dict:
    base = {
        "sheet_id": "sheet123",
        "role_active": None,
        "role_former": None,
        "log_channel": None,
        "processed_charges": {},
        "annual_tracking": {},
    }
    if overrides:
        base.update(overrides)
    return base


def _make_config_mock(guild_data: dict | None = None) -> MagicMock:
    """Build a Config mock whose guild group returns the given data dict."""
    data = _build_guild_config(guild_data)
    config = MagicMock(spec=Config)

    guild_group = MagicMock()
    for key, value in data.items():
        attr = MagicMock()
        attr.__call__ = lambda self, *a, val=value, **kw: AsyncMock(return_value=val)()
        setattr(guild_group, key, AsyncMock(return_value=value))
        # Also add a .set() on each attribute for mutation tests
        setattr(guild_group, key, _make_config_attr(value))

    config.guild.return_value = guild_group
    config.register_guild = MagicMock()
    config.register_user = MagicMock()
    return config


def _make_config_attr(value: object) -> MagicMock:
    """Return an AsyncMock that acts as both ``await attr()`` and ``attr.set(v)``."""
    attr = AsyncMock(return_value=value)
    attr.set = AsyncMock()
    return attr


def _make_patron_cog(bot: MagicMock | None = None, guild_data: dict | None = None) -> Patron:
    """Construct a Patron instance with mocked Config and bot, without starting bg_task."""
    if bot is None:
        bot = MagicMock()
        bot.loop = asyncio.get_event_loop()
        bot.guilds = []

    config_mock = _make_config_mock(guild_data)

    with (
        patch("patron.patron.Config.get_conf", return_value=config_mock),
        patch.object(bot.loop, "create_task", return_value=MagicMock()),
    ):
        cog = Patron(bot)  # type: ignore[arg-type]

    cog.config = config_mock
    return cog


# ---------------------------------------------------------------------------
# parse_amount tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("5.00", 5.0),
        ("$5.00", 5.0),
        ("€5,00", 5.0),
        ("1,000.00", 1000.0),
        ("1.000,00", 1000.0),
        ("10", 10.0),
        ("", 0.0),
        ("abc", 0.0),
        ("$0", 0.0),
        ("20.50", 20.5),
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
    ],
)
def test_parse_amount(raw: str, expected: float) -> None:
    cog = _make_patron_cog()
    assert cog.parse_amount(raw) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# calculate_reward tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount, expected",
    [
        (1.0, 3000),  # 1 * 3000 * 1.0
        (4.0, 12000),  # 4 * 3000 * 1.0 (below 5 threshold)
        (5.0, 15750),  # 5 * 3000 * 1.05
        (9.0, 28350),  # 9 * 3000 * 1.05
        (10.0, 33000),  # 10 * 3000 * 1.10
        (19.0, 62700),  # 19 * 3000 * 1.10
        (20.0, 69000),  # 20 * 3000 * 1.15
        (39.0, 134550),  # 39 * 3000 * 1.15
        (40.0, 144000),  # 40 * 3000 * 1.20
        (100.0, 360000),  # 100 * 3000 * 1.20
    ],
)
def test_calculate_reward(amount: float, expected: int) -> None:
    cog = _make_patron_cog()
    assert cog.calculate_reward(amount) == expected


# ---------------------------------------------------------------------------
# award_currency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_award_currency_calls_unicornia() -> None:
    """award_currency delegates to Unicornia.add_balance with correct args."""
    cog = _make_patron_cog()

    unicornia = MagicMock()
    unicornia.add_balance = AsyncMock(return_value=True)
    cog.bot.get_cog.return_value = unicornia

    guild = MagicMock(spec=discord.Guild)
    guild.get_channel.return_value = None
    cast(MagicMock, cog.config.guild).return_value.log_channel = AsyncMock(return_value=None)

    member = MagicMock(spec=discord.Member)
    member.id = 1
    member.name = "Alice"

    await cog.award_currency(guild, member, 15000, "Test reason")

    unicornia.add_balance.assert_awaited_once_with(member.id, 15000, reason="Patreon: Test reason", source="patron")


@pytest.mark.asyncio
async def test_award_currency_no_unicornia_does_not_raise() -> None:
    cog = _make_patron_cog()
    cog.bot.get_cog.return_value = None

    guild = MagicMock(spec=discord.Guild)
    member = MagicMock(spec=discord.Member)
    member.id = 1
    member.name = "Bob"

    await cog.award_currency(guild, member, 5000, "reason")


@pytest.mark.asyncio
async def test_award_currency_logs_to_channel_when_configured() -> None:
    """When a log channel is configured and found, a message is sent."""
    cog = _make_patron_cog()

    unicornia = MagicMock()
    unicornia.add_balance = AsyncMock(return_value=True)
    cog.bot.get_cog.return_value = unicornia

    log_channel = MagicMock(spec=discord.TextChannel)
    log_channel.send = AsyncMock()

    guild = MagicMock(spec=discord.Guild)
    guild.get_channel.return_value = log_channel
    cast(MagicMock, cog.config.guild).return_value.log_channel = AsyncMock(return_value=999)

    member = MagicMock(spec=discord.Member)
    member.id = 2
    member.name = "Carol"
    member.mention = "<@2>"

    await cog.award_currency(guild, member, 9000, "Monthly")

    log_channel.send.assert_awaited_once()
    sent_text: str = log_channel.send.call_args[0][0]
    assert "9000" in sent_text
    assert "Monthly" in sent_text


# ---------------------------------------------------------------------------
# _process_sheet_logic tests
# ---------------------------------------------------------------------------


def _make_guild(members: list[discord.Member] | None = None) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.name = "TestGuild"
    guild.members = members or []
    guild.get_role.return_value = None
    return guild


def _make_member_obj(name: str, uid: int = 1, roles: list | None = None) -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.id = uid
    m.name = name
    m.roles = roles or []
    m.add_roles = AsyncMock()
    m.remove_roles = AsyncMock()
    return m


@pytest.mark.asyncio
async def test_process_sheet_logic_adds_active_role() -> None:
    """An active-patron row whose member has no active role gets the role added."""
    cog = _make_patron_cog()

    role_active = MagicMock(spec=discord.Role)
    role_active.id = 10
    role_active.members = []

    role_former = MagicMock(spec=discord.Role)
    role_former.id = 20

    member = _make_member_obj("alice", uid=1, roles=[])
    guild = _make_guild(members=[member])
    guild.get_role.side_effect = lambda rid: role_active if rid == 10 else role_former

    records = [
        {
            "Discord": "alice",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    cfg = cast(MagicMock, cog.config.guild).return_value
    cfg.role_active = AsyncMock(return_value=10)
    cfg.role_former = AsyncMock(return_value=20)
    cfg.processed_charges = AsyncMock(return_value={})
    cfg.annual_tracking = AsyncMock(return_value={})
    cfg.log_channel = AsyncMock(return_value=None)
    cfg.processed_charges.set = AsyncMock()
    cfg.annual_tracking.set = AsyncMock()

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock()

    await cog._process_sheet_logic(guild, "sheet123")

    member.add_roles.assert_awaited_once_with(role_active, reason="Patron Sync: Active")
    cog.award_currency.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_sheet_logic_removes_active_role_on_lapse() -> None:
    """A former-patron row removes the active role and adds the former role."""
    cog = _make_patron_cog()

    role_active = MagicMock(spec=discord.Role)
    role_active.id = 10
    role_active.members = []

    role_former = MagicMock(spec=discord.Role)
    role_former.id = 20

    member = _make_member_obj("bob", uid=2, roles=[role_active])
    guild = _make_guild(members=[member])
    guild.get_role.side_effect = lambda rid: role_active if rid == 10 else role_former

    records = [
        {
            "Discord": "bob",
            "Patron Status": "Former Patron",
            "Last Charge Date": "",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    cfg = cast(MagicMock, cog.config.guild).return_value
    cfg.role_active = AsyncMock(return_value=10)
    cfg.role_former = AsyncMock(return_value=20)
    cfg.processed_charges = AsyncMock(return_value={})
    cfg.annual_tracking = AsyncMock(return_value={})
    cfg.processed_charges.set = AsyncMock()
    cfg.annual_tracking.set = AsyncMock()

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock()

    await cog._process_sheet_logic(guild, "sheet123")

    member.remove_roles.assert_awaited_once_with(role_active, reason="Patron Sync: No longer Active")
    member.add_roles.assert_awaited_once_with(role_former, reason="Patron Sync: No longer Active")


@pytest.mark.asyncio
async def test_process_sheet_logic_skips_duplicate_charge() -> None:
    """No currency is awarded if the last charge date is already recorded."""
    cog = _make_patron_cog()

    member = _make_member_obj("carol", uid=3)
    guild = _make_guild(members=[member])
    guild.get_role.return_value = None

    records = [
        {
            "Discord": "carol",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    cfg = cast(MagicMock, cog.config.guild).return_value
    cfg.role_active = AsyncMock(return_value=None)
    cfg.role_former = AsyncMock(return_value=None)
    cfg.processed_charges = AsyncMock(return_value={"carol": "2024-01-01"})
    cfg.annual_tracking = AsyncMock(return_value={})
    cfg.processed_charges.set = AsyncMock()
    cfg.annual_tracking.set = AsyncMock()

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock()

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sheet_logic_skips_empty_username() -> None:
    """Rows with no Discord username are silently skipped."""
    cog = _make_patron_cog()

    guild = _make_guild(members=[])
    guild.get_role.return_value = None

    records = [
        {
            "Discord": "",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    cfg = cast(MagicMock, cog.config.guild).return_value
    cfg.role_active = AsyncMock(return_value=None)
    cfg.role_former = AsyncMock(return_value=None)
    cfg.processed_charges = AsyncMock(return_value={})
    cfg.annual_tracking = AsyncMock(return_value={})

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock()

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sheet_logic_skips_member_not_in_guild() -> None:
    """If the Discord username doesn't match any guild member, no action is taken."""
    cog = _make_patron_cog()

    guild = _make_guild(members=[])  # empty — no match
    guild.get_role.return_value = None

    records = [
        {
            "Discord": "ghost",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    cfg = cast(MagicMock, cog.config.guild).return_value
    cfg.role_active = AsyncMock(return_value=None)
    cfg.role_former = AsyncMock(return_value=None)
    cfg.processed_charges = AsyncMock(return_value={})
    cfg.annual_tracking = AsyncMock(return_value={})

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock()

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sheet_logic_aborts_on_sheet_error() -> None:
    """If connect_to_sheet returns an error, _process_sheet_logic returns early."""
    cog = _make_patron_cog()
    guild = _make_guild()

    cog.connect_to_sheet = AsyncMock(return_value=(None, "connection refused"))
    cog.award_currency = AsyncMock()

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sheet_logic_annual_monthly_distribution() -> None:
    """For an annual patron with prior tracking, award if 30 days have elapsed."""
    cog = _make_patron_cog()

    member = _make_member_obj("dave", uid=4)
    guild = _make_guild(members=[member])
    guild.get_role.return_value = None

    # Anchor 31 days ago — next due has passed, last award 31 days ago (safe)
    anchor = (datetime.utcnow() - timedelta(days=31)).isoformat()
    last_award = (datetime.utcnow() - timedelta(days=31)).isoformat()

    records = [
        {
            "Discord": "dave",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "120",
            "Charge Frequency": "Annual",
        }
    ]

    cfg = cast(MagicMock, cog.config.guild).return_value
    cfg.role_active = AsyncMock(return_value=None)
    cfg.role_former = AsyncMock(return_value=None)
    cfg.processed_charges = AsyncMock(return_value={"dave": "2024-01-01"})
    cfg.annual_tracking = AsyncMock(
        return_value={"dave": {"anchor_date": anchor, "months_paid": 1, "last_award": last_award}}
    )
    cfg.processed_charges.set = AsyncMock()
    cfg.annual_tracking.set = AsyncMock()

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock()

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_awaited_once()
    call_args = cog.award_currency.call_args
    assert "Month 2/12" in call_args[0][3]


@pytest.mark.asyncio
async def test_process_sheet_logic_annual_skips_if_awarded_recently() -> None:
    """Annual recurring award is skipped if last_award was less than 25 days ago."""
    cog = _make_patron_cog()

    member = _make_member_obj("eve", uid=5)
    guild = _make_guild(members=[member])
    guild.get_role.return_value = None

    anchor = (datetime.utcnow() - timedelta(days=35)).isoformat()
    last_award = (datetime.utcnow() - timedelta(days=10)).isoformat()  # too recent

    records = [
        {
            "Discord": "eve",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "120",
            "Charge Frequency": "Annual",
        }
    ]

    cfg = cast(MagicMock, cog.config.guild).return_value
    cfg.role_active = AsyncMock(return_value=None)
    cfg.role_former = AsyncMock(return_value=None)
    cfg.processed_charges = AsyncMock(return_value={"eve": "2024-01-01"})
    cfg.annual_tracking = AsyncMock(
        return_value={"eve": {"anchor_date": anchor, "months_paid": 1, "last_award": last_award}}
    )
    cfg.processed_charges.set = AsyncMock()
    cfg.annual_tracking.set = AsyncMock()

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock()

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sheet_logic_reverse_sync_downgrades_absent_member() -> None:
    """Members with active role not found in the active sheet list get downgraded."""
    cog = _make_patron_cog()

    role_active = MagicMock(spec=discord.Role)
    role_active.id = 10

    role_former = MagicMock(spec=discord.Role)
    role_former.id = 20

    # frank has the active role but is NOT in the sheet at all
    frank = _make_member_obj("frank", uid=6, roles=[role_active])
    role_active.members = [frank]

    guild = _make_guild(members=[frank])
    guild.get_role.side_effect = lambda rid: role_active if rid == 10 else role_former

    # Sheet has no rows (empty)
    records: list[dict] = []

    cfg = cast(MagicMock, cog.config.guild).return_value
    cfg.role_active = AsyncMock(return_value=10)
    cfg.role_former = AsyncMock(return_value=20)
    cfg.processed_charges = AsyncMock(return_value={})
    cfg.annual_tracking = AsyncMock(return_value={})
    cfg.processed_charges.set = AsyncMock()
    cfg.annual_tracking.set = AsyncMock()

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock()

    await cog._process_sheet_logic(guild, "sheet123")

    frank.remove_roles.assert_awaited_once_with(role_active, reason="Patron Sync: Not in Active list")
    frank.add_roles.assert_awaited_once_with(role_former, reason="Patron Sync: Not in Active list")


# ---------------------------------------------------------------------------
# process_sheet lock guard test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_sheet_skips_when_locked() -> None:
    """process_sheet returns immediately if the lock is already held."""
    cog = _make_patron_cog()
    cog._process_sheet_logic = AsyncMock()

    guild = MagicMock(spec=discord.Guild)

    async with cog.lock:
        # Lock is held — process_sheet should bail out without calling logic
        await cog.process_sheet(guild, "sheet123")

    cog._process_sheet_logic.assert_not_awaited()


# ---------------------------------------------------------------------------
# connect_to_sheet: missing credentials
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_to_sheet_missing_creds_returns_error() -> None:
    """connect_to_sheet returns (None, error_msg) when service_account.json is absent."""
    cog = _make_patron_cog()

    with patch.object(Path, "exists", return_value=False):
        result, error = await cog.connect_to_sheet("sheet123")

    assert result is None
    assert error is not None
    assert "service_account.json" in error


# ---------------------------------------------------------------------------
# dpytest integration tests — bot commands
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def dpytest_bot() -> AsyncGenerator[dpy_commands.Bot, None]:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True

    real_bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await real_bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(real_bot)

    yield real_bot

    await dpytest.empty_queue()


@pytest.mark.asyncio
async def test_dpytest_patronset_setup_sets_sheet_id(dpytest_bot: dpy_commands.Bot) -> None:
    """set_sheet_id stores the sheet_id in config when called directly.

    Note: invoking Redbot owner-gated commands via dpytest.message fails because
    the bare dpy_commands.Bot context lacks ``permission_state``.  We call the
    command callback directly, matching the pattern used across this project.
    """
    config_mock = _make_config_mock()
    config_mock.guild.return_value.sheet_id.set = AsyncMock()

    with (
        patch("patron.patron.Config.get_conf", return_value=config_mock),
        patch.object(dpytest_bot.loop, "create_task", return_value=MagicMock()),
    ):
        cog = Patron(dpytest_bot)  # type: ignore[arg-type]
        cog.config = config_mock

    await dpytest_bot.add_cog(cog)

    guild = dpytest.get_config().guilds[0]
    ctx = MagicMock()
    ctx.guild = guild
    ctx.send = AsyncMock()

    await cog.set_sheet_id(ctx, "mysheet42")  # type: ignore[arg-type]

    config_mock.guild.return_value.sheet_id.set.assert_awaited_once_with("mysheet42")
    ctx.send.assert_awaited_once()
    assert "mysheet42" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_dpytest_patronset_sync_no_sheet_id(dpytest_bot: dpy_commands.Bot) -> None:
    """manual_sync sends 'Sheet ID not set' when no sheet_id is configured."""
    config_mock = _make_config_mock()
    config_mock.guild.return_value.sheet_id = AsyncMock(return_value=None)

    with (
        patch("patron.patron.Config.get_conf", return_value=config_mock),
        patch.object(dpytest_bot.loop, "create_task", return_value=MagicMock()),
    ):
        cog = Patron(dpytest_bot)  # type: ignore[arg-type]
        cog.config = config_mock

    await dpytest_bot.add_cog(cog)

    guild = dpytest.get_config().guilds[0]
    ctx = MagicMock()
    ctx.guild = guild
    ctx.send = AsyncMock()
    ctx.typing = MagicMock()
    ctx.typing.return_value.__aenter__ = AsyncMock(return_value=None)
    ctx.typing.return_value.__aexit__ = AsyncMock(return_value=False)

    await cog.manual_sync(ctx)  # type: ignore[arg-type]

    # First call: "Starting sync process...", second: "Sheet ID not set."
    assert ctx.send.await_count == 2
    messages = [call[0][0] for call in ctx.send.call_args_list]
    assert any("Sheet ID not set" in m for m in messages)


@pytest.mark.asyncio
async def test_dpytest_patronset_sync_already_locked(dpytest_bot: dpy_commands.Bot) -> None:
    """manual_sync sends 'already in progress' when the lock is held."""
    config_mock = _make_config_mock()

    with (
        patch("patron.patron.Config.get_conf", return_value=config_mock),
        patch.object(dpytest_bot.loop, "create_task", return_value=MagicMock()),
    ):
        cog = Patron(dpytest_bot)  # type: ignore[arg-type]
        cog.config = config_mock

    await dpytest_bot.add_cog(cog)

    ctx = MagicMock()
    ctx.guild = dpytest.get_config().guilds[0]
    ctx.send = AsyncMock()

    async with cog.lock:
        await cog.manual_sync(ctx)  # type: ignore[arg-type]

    ctx.send.assert_awaited_once()
    assert "already in progress" in ctx.send.call_args[0][0].lower()
