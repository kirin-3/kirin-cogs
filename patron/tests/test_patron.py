"""Tests for the Patron cog.

Unit tests cover:
- parse_amount: localized currency string parsing to exact Decimal values
- calculate_reward: tier/bonus calculation with Decimal arithmetic
- _process_sheet_logic: role assignment, idempotent currency awarding, dedup,
  annual tracking, Discord-ID and legacy-username matching
- award_currency: Unicornia operation-API integration (settled/duplicate/failure)
- process_sheet: lock guard
- Task lifecycle: sync task created in cog_load, cancelled/gathered on unload

dpytest integration tests cover:
- patronset setup / logchannel / sync commands via bot dispatch
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
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


def _make_config_attr(value: object) -> MagicMock:
    """Return an AsyncMock that acts as both ``await attr()`` and ``attr.set(v)``."""
    attr = AsyncMock(return_value=value)
    attr.set = AsyncMock()
    return attr


def _make_config_mock(guild_data: dict | None = None) -> MagicMock:
    """Build a Config mock whose guild group returns the given data dict."""
    data = _build_guild_config(guild_data)
    config = MagicMock(spec=Config)

    guild_group = MagicMock()
    for key, value in data.items():
        setattr(guild_group, key, _make_config_attr(value))

    config.guild.return_value = guild_group
    config.register_guild = MagicMock()
    config.register_user = MagicMock()
    config.all_guilds = AsyncMock(return_value={})
    return config


def _make_patron_cog(bot: MagicMock | None = None, guild_data: dict | None = None) -> Patron:
    """Construct a Patron instance with mocked Config and bot.

    The sync task is created in ``cog_load`` (not ``__init__``), so plain
    construction never touches the event loop.
    """
    if bot is None:
        bot = MagicMock()
        bot.guilds = []

    config_mock = _make_config_mock(guild_data)

    with patch("patron.patron.Config.get_conf", return_value=config_mock):
        cog = Patron(bot)  # type: ignore[arg-type]

    cog.config = config_mock
    return cog


def _outcome(state: str = "settled") -> SimpleNamespace:
    return SimpleNamespace(state=state, new_balance=0, amount=0, result={})


# ---------------------------------------------------------------------------
# parse_amount tests (Decimal, localized inputs)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("5.00", "5.00"),
        ("$5.00", "5.00"),
        ("€5,00", "5.00"),
        ("1,000.00", "1000.00"),
        ("1.000,00", "1000.00"),
        ("10", "10"),
        ("", "0"),
        ("abc", "0"),
        ("$0", "0"),
        ("20.50", "20.50"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("0.1", "0.1"),
        ("2,5", "2.5"),
    ],
)
def test_parse_amount(raw: str, expected: str) -> None:
    cog = _make_patron_cog()
    result = cog.parse_amount(raw)
    assert isinstance(result, Decimal)
    assert result == Decimal(expected)


def test_parse_amount_is_exact_not_binary_float() -> None:
    """0.1 + 0.2 style float errors must not leak into reward math."""
    cog = _make_patron_cog()
    assert cog.parse_amount("0.1") + cog.parse_amount("0.2") == Decimal("0.3")


# ---------------------------------------------------------------------------
# calculate_reward tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount, expected",
    [
        ("1.0", 3000),  # 1 * 3000 * 1.0
        ("4.0", 12000),  # 4 * 3000 * 1.0 (below 5 threshold)
        ("5.0", 15750),  # 5 * 3000 * 1.05
        ("9.0", 28350),  # 9 * 3000 * 1.05
        ("10.0", 33000),  # 10 * 3000 * 1.10
        ("19.0", 62700),  # 19 * 3000 * 1.10
        ("20.0", 69000),  # 20 * 3000 * 1.15
        ("39.0", 134550),  # 39 * 3000 * 1.15
        ("40.0", 144000),  # 40 * 3000 * 1.20
        ("100.0", 360000),  # 100 * 3000 * 1.20
        ("8.33", 26240),  # 8.33 * 3000 * 1.05 = 26239.5 -> half-up 26240
    ],
)
def test_calculate_reward(amount: str, expected: int) -> None:
    cog = _make_patron_cog()
    assert cog.calculate_reward(Decimal(amount)) == expected


# ---------------------------------------------------------------------------
# award_currency tests (operation API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_award_currency_calls_unicornia_operation_api() -> None:
    """award_currency delegates to Unicornia.apply_operation with the payment key."""
    cog = _make_patron_cog()

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=_outcome("settled"))
    cog.bot.get_cog.return_value = unicornia

    guild = MagicMock(spec=discord.Guild)
    guild.id = 777
    guild.get_channel.return_value = None
    cast(MagicMock, cog.config.guild).return_value.log_channel = AsyncMock(return_value=None)

    member = MagicMock(spec=discord.Member)
    member.id = 1
    member.name = "Alice"

    awarded = await cog.award_currency(guild, member, 15000, "Test reason", operation_key="patron:777:1:2024-01-01")

    assert awarded is True
    unicornia.apply_operation.assert_awaited_once_with(
        key="patron:777:1:2024-01-01",
        user_id=member.id,
        amount=15000,
        direction="credit",
        source="patron",
        guild_id=777,
        reason="Patreon: Test reason",
    )


@pytest.mark.asyncio
async def test_award_currency_no_unicornia_returns_false() -> None:
    cog = _make_patron_cog()
    cog.bot.get_cog.return_value = None

    guild = MagicMock(spec=discord.Guild)
    member = MagicMock(spec=discord.Member)
    member.id = 1
    member.name = "Bob"

    awarded = await cog.award_currency(guild, member, 5000, "reason", operation_key="k")
    assert awarded is False


@pytest.mark.asyncio
async def test_award_currency_duplicate_is_advanceable_but_not_announced() -> None:
    """A duplicate settlement allows advancement without a second channel log."""
    cog = _make_patron_cog()

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=_outcome("duplicate"))
    cog.bot.get_cog.return_value = unicornia

    log_channel = MagicMock(spec=discord.TextChannel)
    log_channel.send = AsyncMock()

    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    guild.get_channel.return_value = log_channel
    cast(MagicMock, cog.config.guild).return_value.log_channel = AsyncMock(return_value=999)

    member = MagicMock(spec=discord.Member)
    member.id = 2
    member.name = "Carol"
    member.mention = "<@2>"

    awarded = await cog.award_currency(guild, member, 9000, "Monthly", operation_key="k2")

    assert awarded is True
    log_channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_award_currency_logs_to_channel_when_settled() -> None:
    """When a log channel is configured and found, a message is sent on fresh settles."""
    cog = _make_patron_cog()

    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=_outcome("settled"))
    cog.bot.get_cog.return_value = unicornia

    log_channel = MagicMock(spec=discord.TextChannel)
    log_channel.send = AsyncMock()

    guild = MagicMock(spec=discord.Guild)
    guild.id = 5
    guild.get_channel.return_value = log_channel
    cast(MagicMock, cog.config.guild).return_value.log_channel = AsyncMock(return_value=999)

    member = MagicMock(spec=discord.Member)
    member.id = 2
    member.name = "Carol"
    member.mention = "<@2>"

    awarded = await cog.award_currency(guild, member, 9000, "Monthly", operation_key="k3")

    assert awarded is True
    log_channel.send.assert_awaited_once()
    sent_text: str = log_channel.send.call_args[0][0]
    assert "9000" in sent_text
    assert "Monthly" in sent_text


@pytest.mark.asyncio
async def test_award_currency_not_ready_returns_false() -> None:
    cog = _make_patron_cog()
    unicornia = MagicMock()
    unicornia.apply_operation = AsyncMock(return_value=None)
    cog.bot.get_cog.return_value = unicornia

    member = MagicMock(spec=discord.Member)
    member.id = 1
    member.name = "Dave"

    awarded = await cog.award_currency(MagicMock(spec=discord.Guild), member, 100, "r", operation_key="k4")
    assert awarded is False


# ---------------------------------------------------------------------------
# _process_sheet_logic tests
# ---------------------------------------------------------------------------


def _make_guild(members: list[discord.Member] | None = None) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 4242
    guild.name = "TestGuild"
    guild.members = members or []
    guild.get_role.return_value = None
    guild.get_member.side_effect = lambda uid: discord.utils.get(guild.members, id=uid)
    return guild


def _make_member_obj(name: str, uid: int = 1, roles: list | None = None) -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.id = uid
    m.name = name
    m.roles = roles or []
    m.add_roles = AsyncMock()
    m.remove_roles = AsyncMock()
    return m


def _configure_sheet_cfg(cog: Patron, *, charges: dict | None = None, tracking: dict | None = None) -> MagicMock:
    cfg = cast(MagicMock, cog.config.guild).return_value
    cfg.role_active = AsyncMock(return_value=None)
    cfg.role_former = AsyncMock(return_value=None)
    cfg.processed_charges = AsyncMock(return_value=dict(charges or {}))
    cfg.annual_tracking = AsyncMock(return_value=dict(tracking or {}))
    cfg.processed_charges.set = AsyncMock()
    cfg.annual_tracking.set = AsyncMock()
    return cfg


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

    cfg = _configure_sheet_cfg(cog)
    cfg.role_active = AsyncMock(return_value=10)
    cfg.role_former = AsyncMock(return_value=20)
    cfg.log_channel = AsyncMock(return_value=None)

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    member.add_roles.assert_awaited_once_with(role_active, reason="Patron Sync: Active")
    cog.award_currency.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_sheet_logic_resolves_discord_id_rows() -> None:
    """A row whose Discord column holds a member ID resolves without username matching."""
    cog = _make_patron_cog()

    member = _make_member_obj("alice_renamed", uid=123456789, roles=[])
    guild = _make_guild(members=[member])

    records = [
        {
            "Discord": "123456789",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    cfg = _configure_sheet_cfg(cog)
    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    # Charge recorded under the canonical member-ID key
    cfg.processed_charges.set.assert_awaited_once()
    written = cfg.processed_charges.set.call_args[0][0]
    assert written == {"123456789": "2024-01-01"}

    # Payment identity key: patron:{guild}:{member}:{charge_date}
    operation_key = cog.award_currency.call_args.kwargs["operation_key"]
    assert operation_key == "patron:4242:123456789:2024-01-01"


@pytest.mark.asyncio
async def test_process_sheet_logic_legacy_username_charge_lookup() -> None:
    """Legacy username-keyed charge records still dedup and are adopted to ID keys."""
    cog = _make_patron_cog()

    member = _make_member_obj("carol", uid=3)
    guild = _make_guild(members=[member])

    records = [
        {
            "Discord": "carol",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    # Legacy record keyed by username suppresses a duplicate award
    _configure_sheet_cfg(cog, charges={"carol": "2024-01-01"})

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_not_awaited()


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

    cfg = _configure_sheet_cfg(cog)
    cfg.role_active = AsyncMock(return_value=10)
    cfg.role_former = AsyncMock(return_value=20)

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    member.remove_roles.assert_awaited_once_with(role_active, reason="Patron Sync: No longer Active")
    member.add_roles.assert_awaited_once_with(role_former, reason="Patron Sync: No longer Active")


@pytest.mark.asyncio
async def test_process_sheet_logic_skips_empty_identifier() -> None:
    """Rows with no Discord identifier are silently skipped."""
    cog = _make_patron_cog()

    guild = _make_guild(members=[])

    records = [
        {
            "Discord": "",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    _configure_sheet_cfg(cog)

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sheet_logic_skips_member_not_in_guild() -> None:
    """If the identifier doesn't match any guild member, no action is taken."""
    cog = _make_patron_cog()

    guild = _make_guild(members=[])  # empty — no match

    records = [
        {
            "Discord": "ghost",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    _configure_sheet_cfg(cog)

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sheet_logic_aborts_on_sheet_error() -> None:
    """If connect_to_sheet returns an error, _process_sheet_logic returns early."""
    cog = _make_patron_cog()
    guild = _make_guild()

    cog.connect_to_sheet = AsyncMock(return_value=(None, "connection refused"))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sheet_logic_no_advance_when_unsettled() -> None:
    """If Unicornia cannot settle, the charge stays unprocessed for the next sync."""
    cog = _make_patron_cog()

    member = _make_member_obj("zoe", uid=9)
    guild = _make_guild(members=[member])

    records = [
        {
            "Discord": "zoe",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    cfg = _configure_sheet_cfg(cog)

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=False)  # Unicornia unavailable/failed

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_awaited_once()
    cfg.processed_charges.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_sheet_logic_crash_window_retry_marks_processed_once() -> None:
    """Crash after Unicornia commit but before Config write: retry advances without double credit."""
    cog = _make_patron_cog()

    member = _make_member_obj("mia", uid=11)
    guild = _make_guild(members=[member])

    records = [
        {
            "Discord": "mia",
            "Patron Status": "Active Patron",
            "Last Charge Date": "2024-01-01",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    cfg = _configure_sheet_cfg(cog)

    # First sync: Unicornia settles, but the Config write crashes.
    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)
    cfg.processed_charges.set = AsyncMock(side_effect=RuntimeError("config store crashed"))

    await cog._process_sheet_logic(guild, "sheet123")
    assert cog.award_currency.await_count == 1

    # Second sync: award_currency (now backed by the idempotent API) reports
    # the operation as a duplicate settlement and the charge is recorded.
    cfg = _configure_sheet_cfg(cog)
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    assert cog.award_currency.await_count == 1
    cfg.processed_charges.set.assert_awaited_once()
    written = cfg.processed_charges.set.call_args[0][0]
    assert written == {"11": "2024-01-01"}


@pytest.mark.asyncio
async def test_process_sheet_logic_annual_monthly_distribution() -> None:
    """For an annual patron with prior tracking, award if 30 days have elapsed."""
    cog = _make_patron_cog()

    member = _make_member_obj("dave", uid=4)
    guild = _make_guild(members=[member])

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

    _configure_sheet_cfg(
        cog,
        charges={"4": "2024-01-01"},
        tracking={"4": {"anchor_date": anchor, "months_paid": 1, "last_award": last_award}},
    )

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    cog.award_currency.assert_awaited_once()
    call_args = cog.award_currency.call_args
    assert "Month 2/12" in call_args[0][3]
    assert call_args.kwargs["operation_key"] == "patron:4242:4:2024-01-01:m2"


@pytest.mark.asyncio
async def test_process_sheet_logic_annual_skips_if_awarded_recently() -> None:
    """Annual recurring award is skipped if last_award was less than 25 days ago."""
    cog = _make_patron_cog()

    member = _make_member_obj("eve", uid=5)
    guild = _make_guild(members=[member])

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

    _configure_sheet_cfg(
        cog,
        charges={"5": "2024-01-01"},
        tracking={"5": {"anchor_date": anchor, "months_paid": 1, "last_award": last_award}},
    )

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

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

    cfg = _configure_sheet_cfg(cog)
    cfg.role_active = AsyncMock(return_value=10)
    cfg.role_former = AsyncMock(return_value=20)

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    frank.remove_roles.assert_awaited_once_with(role_active, reason="Patron Sync: Not in Active list")
    frank.add_roles.assert_awaited_once_with(role_former, reason="Patron Sync: Not in Active list")


@pytest.mark.asyncio
async def test_reverse_sync_keeps_role_for_legacy_username_row() -> None:
    """A member matched by legacy username is not downgraded by reverse sync."""
    cog = _make_patron_cog()

    role_active = MagicMock(spec=discord.Role)
    role_active.id = 10

    role_former = MagicMock(spec=discord.Role)
    role_former.id = 20

    grace = _make_member_obj("grace", uid=7, roles=[role_active])
    role_active.members = [grace]

    guild = _make_guild(members=[grace])
    guild.get_role.side_effect = lambda rid: role_active if rid == 10 else role_former

    records = [
        {
            "Discord": "grace",  # legacy username row, still active
            "Patron Status": "Active Patron",
            "Last Charge Date": "",
            "Pledge Amount": "5",
            "Charge Frequency": "monthly",
        }
    ]

    cfg = _configure_sheet_cfg(cog)
    cfg.role_active = AsyncMock(return_value=10)
    cfg.role_former = AsyncMock(return_value=20)

    cog.connect_to_sheet = AsyncMock(return_value=(records, None))
    cog.award_currency = AsyncMock(return_value=True)

    await cog._process_sheet_logic(guild, "sheet123")

    grace.remove_roles.assert_not_awaited()


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
# Task lifecycle (cog_load / cog_unload)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cog_load_creates_sync_task_and_unload_cancels_it() -> None:
    """The sync task is owned: created in cog_load, cancelled and gathered on unload."""
    cog = _make_patron_cog()

    async def _never_ending():
        await asyncio.Event().wait()

    cog.sync_loop = _never_ending  # type: ignore[method-assign]

    await cog.cog_load()
    assert cog.bg_task is not None
    assert not cog.bg_task.done()

    await cog.cog_unload()
    assert cog.bg_task is None


@pytest.mark.asyncio
async def test_bg_task_done_callback_logs_exceptions() -> None:
    """A failing background task has its exception retrieved and logged."""
    cog = _make_patron_cog()

    async def _failing():
        raise RuntimeError("boom")

    logged: list[str] = []
    with patch("patron.patron.log.error", side_effect=lambda *a, **kw: logged.append(str(a))):
        await cog.cog_load()
        # cog_load created a task for the real sync_loop; cancel it first
        assert cog.bg_task is not None
        cog.bg_task.cancel()
        await asyncio.gather(cog.bg_task, return_exceptions=True)

        task = asyncio.create_task(_failing())
        task.add_done_callback(cog._on_bg_task_done)
        await asyncio.gather(task, return_exceptions=True)

    assert any("boom" in entry for entry in logged)


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

    with patch("patron.patron.Config.get_conf", return_value=config_mock):
        cog = Patron(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock

    await dpytest_bot.add_cog(cog)
    # cog_load created the real sync task on the running loop; cancel it.
    assert cog.bg_task is not None
    cog.bg_task.cancel()

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

    with patch("patron.patron.Config.get_conf", return_value=config_mock):
        cog = Patron(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock

    await dpytest_bot.add_cog(cog)
    assert cog.bg_task is not None
    cog.bg_task.cancel()

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

    with patch("patron.patron.Config.get_conf", return_value=config_mock):
        cog = Patron(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock

    await dpytest_bot.add_cog(cog)
    assert cog.bg_task is not None
    cog.bg_task.cancel()

    ctx = MagicMock()
    ctx.guild = dpytest.get_config().guilds[0]
    ctx.send = AsyncMock()

    async with cog.lock:
        await cog.manual_sync(ctx)  # type: ignore[arg-type]

    ctx.send.assert_awaited_once()
    assert "already in progress" in ctx.send.call_args[0][0].lower()
