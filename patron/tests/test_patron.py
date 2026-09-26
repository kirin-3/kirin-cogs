"""Tests for the Patron cog: Patreon polling, Buy Me a Coffee webhooks, payouts and role sync."""

import asyncio
import functools
import hashlib
import hmac
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from aiohttp.test_utils import TestClient, TestServer

from patron import patron as patron_module
from patron.api import (
    ApiError,
    PatreonClient,
    PatreonMember,
    parse_members_page,
    verify_bmc_signature,
)
from patron.patron import (
    GUILD_ID,
    PERIOD_SECONDS,
    Patron,
    add_bmc_member,
    apply_bmc_event,
    calculate_reward,
    merge_patreon,
    periods_due,
    plan_entries,
)
from testutils import DictConfig

NOW = 1_800_000_000.0
DAY = 86400
SECRET = "whsec"


def _state(**buckets: dict) -> dict[str, dict]:
    return {key: dict(buckets.get(key, {})) for key in ("links", "patreon_members", "bmc_members", "bmc_tips")}


def _member(**overrides: Any) -> PatreonMember:
    fields: dict[str, Any] = {
        "id": "m1",
        "name": "Alice",
        "email": "alice@example.com",
        "discord_id": 11,
        "status": "active_patron",
        "last_charge_date": "2026-12-15T00:00:00+00:00",
        "last_charge_status": "Paid",
        "cents": 500,
        "cadence": 1,
    }
    fields.update(overrides)
    return PatreonMember(**fields)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount, expected",
    [
        ("1.0", 3000),
        ("4.0", 12000),
        ("5.0", 15750),
        ("10.0", 33000),
        ("20.0", 69000),
        ("40.0", 144000),
        ("8.33", 26240),  # 26239.5 rounds half-up
    ],
)
def test_calculate_reward(amount: str, expected: int) -> None:
    assert calculate_reward(Decimal(amount)) == expected


def test_periods_due() -> None:
    assert periods_due(NOW, NOW - 1, None) == 0
    assert periods_due(NOW, NOW, None) == 1
    assert periods_due(NOW, NOW + PERIOD_SECONDS, None) == 2
    assert periods_due(NOW, NOW + 40 * PERIOD_SECONDS, 12) == 12


def test_parse_members_page_reads_discord_id_and_tolerates_missing_connections() -> None:
    payload = {
        "data": [
            {
                "id": "a",
                "attributes": {"full_name": "A", "email": "A@X.com", "patron_status": "active_patron"},
                "relationships": {"user": {"data": {"id": "u1", "type": "user"}}},
            },
            {"id": "b", "attributes": {}, "relationships": {"user": {"data": {"id": "u2", "type": "user"}}}},
        ],
        "included": [
            {"id": "u1", "type": "user", "attributes": {"social_connections": {"discord": {"user_id": "123"}}}},
            {"id": "u2", "type": "user", "attributes": {"social_connections": None}},
        ],
    }
    first, second = parse_members_page(payload)
    assert first.discord_id == 123
    assert first.email == "a@x.com"
    assert second.discord_id is None
    assert second.cadence == 1


def test_verify_bmc_signature() -> None:
    body = b'{"a":1}'
    good = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert verify_bmc_signature(body, SECRET, good)
    assert not verify_bmc_signature(body, SECRET, "0" * 64)
    assert not verify_bmc_signature(body, SECRET, "ünicode")


def test_merge_patreon_baseline_counts_current_charge_as_paid() -> None:
    records: dict = {}
    merge_patreon(records, [_member()], NOW, baseline=True)
    assert records["m1"]["paid"] == 1

    merge_patreon(records, [_member(last_charge_date="2027-02-01T00:00:00+00:00")], NOW, baseline=False)
    assert records["m1"]["paid"] == 0
    assert records["m1"]["charge"] == "2027-02-01T00:00:00+00:00"


def test_merge_patreon_ignores_unpaid_charges_and_marks_missing_members() -> None:
    records: dict = {"gone": {"charge": "x", "status": "active_patron"}}
    merge_patreon(records, [_member(last_charge_status="Declined")], NOW, baseline=False)
    assert records["m1"]["charge"] is None
    assert records["gone"]["status"] is None


def test_merge_patreon_annual_charge_runs_twelve_periods() -> None:
    records: dict = {}
    merge_patreon(records, [_member(cadence=12)], NOW, baseline=False)
    assert records["m1"]["periods"] == 12
    assert records["m1"]["paid"] == 0


def _event(event_type: str, created: int = int(NOW), **data: Any) -> dict:
    base = {"id": 7, "supporter_email": "Bob@Example.com", "supporter_name": "Bob", "amount": 5, "status": "active"}
    base.update(data)
    return {"type": event_type, "created": created, "live_mode": True, "data": base}


def test_membership_started_pays_from_first_period() -> None:
    state = _state()
    assert apply_bmc_event(state, _event("membership.started", started_at=int(NOW)), NOW) == "bmc_members"
    rec = state["bmc_members"]["membership:7"]
    assert rec["paid"] == 0
    assert rec["email"] == "bob@example.com"


def test_membership_first_seen_mid_life_is_not_back_paid() -> None:
    state = _state()
    started = int(NOW - 3 * PERIOD_SECONDS - DAY)
    apply_bmc_event(state, _event("membership.updated", started_at=started), NOW)
    assert state["bmc_members"]["membership:7"]["paid"] == 4


def test_stale_membership_event_is_ignored() -> None:
    state = _state()
    apply_bmc_event(state, _event("membership.cancelled", created=int(NOW), status="canceled"), NOW)
    assert apply_bmc_event(state, _event("membership.updated", created=int(NOW) - 60), NOW) is None
    assert state["bmc_members"]["membership:7"]["status"] == "canceled"


def test_webhook_adopts_manual_membership() -> None:
    state = _state()
    add_bmc_member(state, "bob@example.com", 22, Decimal(5), "month", NOW - 3 * PERIOD_SECONDS)
    state["bmc_members"]["manual:bob@example.com"]["paid"] = 4
    apply_bmc_event(state, _event("membership.updated"), NOW)
    assert list(state["bmc_members"]) == ["membership:7"]
    assert state["bmc_members"]["membership:7"]["paid"] == 4
    assert "manual" not in state["bmc_members"]["membership:7"]


def test_tip_and_refund() -> None:
    state = _state()
    apply_bmc_event(state, _event("donation.created", created_at=int(NOW), status="succeeded"), NOW)
    assert state["bmc_tips"]["7"]["paid"] == 0
    apply_bmc_event(state, _event("donation.refunded", status="refunded"), NOW)
    assert state["bmc_tips"]["7"]["refunded"] is True
    (entry,) = plan_entries(state, NOW)
    assert not entry.active and not entry.payable


def test_unhandled_event_changes_nothing() -> None:
    assert apply_bmc_event(_state(), _event("extra_purchase.created"), NOW) is None


def test_add_bmc_member_counts_current_period_and_corrects_in_place() -> None:
    state = _state()
    assert add_bmc_member(state, "bob@example.com", 22, Decimal(5), "month", NOW)
    assert state["links"] == {"bob@example.com": 22}
    (entry,) = plan_entries(state, NOW + PERIOD_SECONDS - 1)
    assert entry.user_id == 22 and entry.active
    assert periods_due(entry.anchor or 0, NOW + PERIOD_SECONDS - 1, None) == 1  # first period already paid

    assert add_bmc_member(state, "bob@example.com", 23, Decimal(60), "year", NOW + DAY)
    rec = state["bmc_members"]["manual:bob@example.com"]
    assert rec["anchor"] == NOW and rec["amount"] == "60" and rec["duration"] == "year"
    assert state["links"]["bob@example.com"] == 23


def test_add_bmc_member_refuses_email_the_webhook_tracks() -> None:
    state = _state()
    apply_bmc_event(state, _event("membership.started"), NOW)
    assert not add_bmc_member(state, "bob@example.com", 22, Decimal(5), "month", NOW)


def test_plan_entries_links_by_email_and_splits_yearly() -> None:
    state = _state(
        links={"bob@example.com": 22},
        bmc_members={
            "membership:7": {
                "email": "bob@example.com",
                "amount": "120",
                "duration": "year",
                "status": "active",
                "anchor": NOW,
                "paid": 0,
            }
        },
        bmc_tips={"9": {"email": "x@example.com", "amount": "5", "created": int(NOW - 31 * DAY), "paid": 0}},
        patreon_members={"free": {"charge": None, "status": None}},
    )
    sub, tip = plan_entries(state, NOW)
    assert sub.user_id == 22
    assert sub.reward == calculate_reward(Decimal("10.00"))
    assert tip.user_id is None
    assert tip.active is False  # tip role lasts 30 days
    assert tip.payable is True


# ---------------------------------------------------------------------------
# Settle: payouts and roles against a dict-backed Config
# ---------------------------------------------------------------------------


@functools.total_ordering
class FakeRole:
    def __init__(self, role_id: int, position: int) -> None:
        self.id = role_id
        self.position = position

    def __lt__(self, other: "FakeRole") -> bool:
        return self.position < other.position

    def __eq__(self, other: object) -> bool:
        return self is other

    __hash__ = object.__hash__


def _discord_member(user_id: int, roles: list | None = None) -> MagicMock:
    member = MagicMock()
    member.id = user_id
    member.mention = f"<@{user_id}>"
    member.roles = list(roles or [])

    async def add_roles(role: FakeRole, reason: str = "") -> None:
        member.roles.append(role)

    async def remove_roles(role: FakeRole, reason: str = "") -> None:
        member.roles.remove(role)

    member.add_roles = AsyncMock(side_effect=add_roles)
    member.remove_roles = AsyncMock(side_effect=remove_roles)
    return member


class World:
    """A cog wired to a DictConfig, a fake guild and a recording Unicornia."""

    def __init__(self, guild_data: dict | None = None, members: list | None = None) -> None:
        self.role_active = FakeRole(1, 5)
        self.role_former = FakeRole(2, 4)
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.send = AsyncMock()
        self.members = {m.id: m for m in members or []}
        self.guild = MagicMock()
        self.guild.id = GUILD_ID
        self.guild.get_member.side_effect = self.members.get
        self.guild.get_role.side_effect = {1: self.role_active, 2: self.role_former}.get
        self.guild.get_channel.side_effect = {50: self.channel}.get
        self.guild.me.guild_permissions.manage_roles = True
        self.guild.me.top_role = FakeRole(3, 10)

        data = {"role_active": 1, "role_former": 2, "log_channel": 50}
        data.update(guild_data or {})
        self.config = DictConfig({"guild": {GUILD_ID: data}})

        self.keys: list[str] = []
        self.unicornia = MagicMock()

        async def apply_operation(**kwargs: Any) -> SimpleNamespace:
            state = "duplicate" if kwargs["key"] in self.keys else "settled"
            self.keys.append(kwargs["key"])
            return SimpleNamespace(state=state)

        self.unicornia.apply_operation = AsyncMock(side_effect=apply_operation)

        bot = MagicMock()
        bot.get_guild.side_effect = {GUILD_ID: self.guild}.get
        bot.get_cog.return_value = self.unicornia
        bot.get_shared_api_tokens = AsyncMock(return_value={"webhook_secret": SECRET})
        with patch("patron.patron.Config.get_conf", return_value=MagicMock()):
            self.cog = Patron(bot)
        self.cog.config = self.config  # type: ignore[assignment]

    def stored(self, key: str) -> Any:
        return self.config.guild_from_id(GUILD_ID).raw()[key]


@pytest.mark.asyncio
async def test_settle_pays_due_periods_once_and_sets_roles() -> None:
    alice = _discord_member(11)
    world = World(
        {
            "patreon_members": {
                "m1": {
                    "charge": "c1",
                    "anchor": NOW - 1,
                    "periods": 12,
                    "paid": 0,
                    "cents": 500,
                    "status": "active_patron",
                    "discord_id": 11,
                }
            }
        },
        [alice],
    )
    with patch("patron.patron.time.time", return_value=NOW + PERIOD_SECONDS):
        await world.cog._settle()
        await world.cog._settle()

    assert world.keys == ["patron:patreon:m1:c1:m1", "patron:patreon:m1:c1:m2"]
    assert world.stored("patreon_members")["m1"]["paid"] == 2
    assert alice.roles == [world.role_active]


@pytest.mark.asyncio
async def test_settle_downgrades_known_supporters_only() -> None:
    lapsed = _discord_member(11)
    stranger = _discord_member(99)
    world = World(
        {"patreon_members": {"m1": {"charge": "c1", "status": "former_patron", "discord_id": 11, "paid": 1}}},
        [lapsed, stranger],
    )
    lapsed.roles.append(world.role_active)
    stranger.roles.append(world.role_active)

    await world.cog._settle()

    assert lapsed.roles == [world.role_former]
    assert stranger.roles == [world.role_active]


@pytest.mark.asyncio
async def test_settle_holds_unlinked_payment_and_notifies_once_then_link_pays() -> None:
    bob = _discord_member(22)
    world = World(
        {"bmc_tips": {"9": {"email": "bob@example.com", "name": "Bob", "amount": "5", "created": int(NOW), "paid": 0}}},
        [bob],
    )
    with patch("patron.patron.time.time", return_value=NOW):
        await world.cog._settle()
        await world.cog._settle()
        assert world.keys == []
        assert world.channel.send.await_count == 1
        assert "bob@example.com" in world.channel.send.call_args[0][0]

        ctx = MagicMock()
        ctx.send = AsyncMock()
        user = MagicMock(spec=discord.User)
        user.id = 22
        user.mention = "<@22>"
        await Patron.link.callback(world.cog, ctx, user, "Bob@Example.com")  # type: ignore[arg-type]

    assert world.keys == ["patron:bmc-tip:9:m1"]
    assert bob.roles == [world.role_active]


@pytest.mark.asyncio
async def test_settle_retries_when_unicornia_does_not_settle() -> None:
    alice = _discord_member(11)
    world = World(
        {
            "patreon_members": {
                "m1": {
                    "charge": "c1",
                    "anchor": NOW,
                    "periods": 1,
                    "paid": 0,
                    "cents": 500,
                    "status": "active_patron",
                    "discord_id": 11,
                }
            }
        },
        [alice],
    )
    world.unicornia.apply_operation = AsyncMock(return_value=None)
    with patch("patron.patron.time.time", return_value=NOW):
        await world.cog._settle()
    assert world.stored("patreon_members")["m1"]["paid"] == 0


@pytest.mark.asyncio
async def test_roles_skipped_without_hierarchy() -> None:
    alice = _discord_member(11)
    world = World(
        {"patreon_members": {"m1": {"charge": "c1", "status": "active_patron", "discord_id": 11, "paid": 1}}},
        [alice],
    )
    world.guild.me.top_role = FakeRole(3, 1)
    await world.cog._settle()
    alice.add_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_award_currency_duplicate_is_not_announced() -> None:
    world = World()
    world.keys.append("k")
    assert await world.cog.award_currency(world.guild, _discord_member(1), 100, "r", operation_key="k")
    world.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_award_currency_without_unicornia_returns_false() -> None:
    world = World()
    world.cog.bot.get_cog.return_value = None
    assert not await world.cog.award_currency(world.guild, _discord_member(1), 100, "r", operation_key="k")


# ---------------------------------------------------------------------------
# Patreon sync and baseline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_sync_baselines_then_new_charge_pays() -> None:
    alice = _discord_member(11)
    world = World({}, [alice])
    world.cog.patreon = MagicMock()
    world.cog.patreon.members = AsyncMock(return_value=[_member()])

    with patch("patron.patron.time.time", return_value=NOW):
        assert await world.cog.sync() is None
        assert world.keys == []
        assert alice.roles == [world.role_active]

        world.cog.patreon.members.return_value = [_member(last_charge_date="2027-01-10T00:00:00+00:00")]
        await world.cog.sync()

    assert world.keys == ["patron:patreon:m1:2027-01-10T00:00:00+00:00:m1"]


@pytest.mark.asyncio
async def test_sync_reports_patreon_error_but_still_settles() -> None:
    world = World()
    world.cog.patreon = MagicMock()
    world.cog.patreon.members = AsyncMock(side_effect=ApiError("nope"))
    world.cog._settle = AsyncMock()  # type: ignore[method-assign]
    assert await world.cog.sync() == "nope"
    world.cog._settle.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_patreon_response_keeps_stored_members() -> None:
    world = World({"patreon_members": {"m1": {"charge": "c1", "status": "active_patron"}}})
    await world.cog._merge_patreon([])
    assert world.stored("patreon_members")["m1"]["status"] == "active_patron"


class _Resp:
    def __init__(self, status: int, body: Any = None) -> None:
        self.status = status
        self.body = body

    async def json(self) -> Any:
        return self.body

    async def __aenter__(self) -> "_Resp":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.mark.asyncio
async def test_patreon_client_refreshes_expired_token() -> None:
    tokens = {"access_token": "old", "refresh_token": "r", "client_id": "c", "client_secret": "s"}
    bot = MagicMock()
    bot.get_shared_api_tokens = AsyncMock(side_effect=lambda _: dict(tokens))

    async def set_tokens(_service: str, **new: str) -> None:
        tokens.update(new)

    bot.set_shared_api_tokens = AsyncMock(side_effect=set_tokens)
    session = MagicMock()
    session.get.side_effect = lambda url, **kw: (
        _Resp(401) if kw["headers"]["Authorization"] == "Bearer old" else _Resp(200, {"data": [{"id": "camp"}]})
    )
    session.post.return_value = _Resp(200, {"access_token": "new", "refresh_token": "r2"})

    client = PatreonClient(bot, session)
    assert await client._campaign() == "camp"
    assert tokens["refresh_token"] == "r2"


@pytest.mark.asyncio
async def test_patreon_client_without_tokens_raises() -> None:
    bot = MagicMock()
    bot.get_shared_api_tokens = AsyncMock(return_value={})
    with pytest.raises(ApiError):
        await PatreonClient(bot, MagicMock()).members()


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------


def _signed(event: dict) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(event).encode()
    return body, {"x-signature-sha256": hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()}


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature_and_ignores_test_events() -> None:
    world = World()
    async with TestClient(TestServer(world.cog.make_app())) as client:
        resp = await client.post("/bmc", data=b"{}", headers={"x-signature-sha256": "bad"})
        assert resp.status == 401

        event = _event("donation.created")
        event["live_mode"] = False
        body, headers = _signed(event)
        resp = await client.post("/bmc", data=body, headers=headers)
        assert resp.status == 200
    assert "bmc_tips" not in world.config.guild_from_id(GUILD_ID).raw()


@pytest.mark.asyncio
async def test_webhook_tip_is_stored_paid_and_refund_logged() -> None:
    bob = _discord_member(22)
    world = World({"links": {"bob@example.com": 22}}, [bob])
    async with TestClient(TestServer(world.cog.make_app())) as client:
        body, headers = _signed(_event("donation.created", created_at=int(NOW), status="succeeded"))
        with patch("patron.patron.time.time", return_value=NOW):
            assert (await client.post("/bmc", data=body, headers=headers)).status == 200
            # BMC retries deliver the same event again
            assert (await client.post("/bmc", data=body, headers=headers)).status == 200
            body, headers = _signed(_event("donation.refunded", status="refunded"))
            assert (await client.post("/bmc", data=body, headers=headers)).status == 200

    assert world.keys == ["patron:bmc-tip:7:m1"]
    assert world.stored("bmc_tips")["7"]["refunded"] is True
    assert "refund" in world.channel.send.call_args[0][0]
    assert bob.roles == [world.role_former]


# ---------------------------------------------------------------------------
# Data deletion and lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_red_delete_data_removes_links_and_records() -> None:
    world = World(
        {
            "links": {"bob@example.com": 22, "other@example.com": 33},
            "bmc_tips": {"9": {"email": "bob@example.com"}, "10": {"email": "other@example.com"}},
            "patreon_members": {"m1": {"discord_id": 22}, "m2": {"discord_id": 33}},
            "processed_charges": {"22": "2024-01-01"},
        }
    )
    await world.cog.red_delete_data_for_user(requester="user", user_id=22)
    assert world.stored("links") == {"other@example.com": 33}
    assert list(world.stored("bmc_tips")) == ["10"]
    assert list(world.stored("patreon_members")) == ["m2"]
    assert world.stored("processed_charges") == {}


@pytest.mark.asyncio
async def test_cog_load_starts_webhook_and_task_and_unload_stops_them() -> None:
    world = World()

    async def never_ending() -> None:
        await asyncio.Event().wait()

    world.cog.sync_loop = never_ending  # type: ignore[method-assign]
    with patch.object(patron_module, "WEBHOOK_PORT", 0):
        await world.cog.cog_load()
    assert world.cog.bg_task is not None and not world.cog.bg_task.done()
    await world.cog.cog_unload()
    assert world.cog.bg_task is None
    assert world.cog._http.closed


@pytest.mark.asyncio
async def test_bmcadd_command_links_and_grants_role_without_paying() -> None:
    bob = _discord_member(22)
    world = World({}, [bob])
    ctx = MagicMock()
    ctx.send = AsyncMock()
    user = MagicMock(spec=discord.User)
    user.id = 22
    user.mention = "<@22>"
    await Patron.bmc_add.callback(world.cog, ctx, user, "Bob@Example.com", "€5,00")  # type: ignore[arg-type]
    assert world.keys == []
    assert bob.roles == [world.role_active]
    assert world.stored("bmc_members")["manual:bob@example.com"]["amount"] == "5.00"


@pytest.mark.asyncio
async def test_manual_sync_reports_busy_lock() -> None:
    world = World()
    ctx = MagicMock()
    ctx.send = AsyncMock()
    async with world.cog.sync_lock:
        await Patron.manual_sync.callback(world.cog, ctx)  # type: ignore[arg-type]
    assert "already in progress" in ctx.send.call_args[0][0]


# ---------------------------------------------------------------------------
# Review fixes
# ---------------------------------------------------------------------------


def test_cancel_at_period_end_stops_pay_but_keeps_role_until_period_end() -> None:
    state = _state(links={"bob@example.com": 22})
    period_end = int(NOW + 10 * DAY)
    apply_bmc_event(
        state, _event("membership.updated", status="active", canceled="true", current_period_end=period_end), NOW
    )
    (entry,) = plan_entries(state, NOW)
    assert not entry.payable and entry.active
    (entry,) = plan_entries(state, period_end + 1)
    assert not entry.active


def test_staff_link_overrides_patreon_discord_connection() -> None:
    state = _state(
        links={"alice@example.com": 99},
        patreon_members={"m1": {"charge": "c", "email": "alice@example.com", "discord_id": 11}},
    )
    (entry,) = plan_entries(state, NOW)
    assert entry.user_id == 99


@pytest.mark.asyncio
async def test_empty_first_sync_does_not_baseline() -> None:
    world = World()
    await world.cog._merge_patreon([])
    assert not world.config.guild_from_id(GUILD_ID).raw().get("patreon_baselined")


@pytest.mark.asyncio
async def test_syncs_never_overlap() -> None:
    world = World()
    running = 0
    peak = 0

    async def members() -> list[PatreonMember]:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return [_member()]

    world.cog.patreon = MagicMock()
    world.cog.patreon.members = members
    await asyncio.gather(world.cog.sync(), world.cog.sync())
    assert peak == 1


@pytest.mark.asyncio
async def test_unlinked_lists_only_current_or_held() -> None:
    world = World(
        {
            "patreon_members": {
                "old": {"charge": "c", "status": "former_patron", "email": "old@example.com", "paid": 1},
                "new": {"charge": "c", "status": "active_patron", "email": "new@example.com", "paid": 1},
            }
        }
    )
    ctx = MagicMock()
    ctx.send = AsyncMock()
    await Patron.list_unlinked.callback(world.cog, ctx)  # type: ignore[arg-type]
    text = ctx.send.call_args[0][0]
    assert "new@example.com" in text
    assert "old@example.com" not in text
