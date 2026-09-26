"""Supporter roles and currency rewards from Patreon (polled hourly) and Buy Me a Coffee (webhooks).

Every payment is keyed by a stable operation key and paid through Unicornia's idempotent operation API, so retries,
restarts and replayed webhooks never credit a payment twice. Recurring support pays once per 30-day period.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import aiohttp
import discord
from aiohttp import web
from redbot.core import Config, checks, commands
from redbot.core.errors import CogLoadError
from redbot.core.utils.chat_formatting import escape, pagify

from .api import (
    ApiError,
    PatreonClient,
    PatreonMember,
    normalize_email,
    verify_bmc_signature,
)
from .migrations import migrate_guild_schemas

log = logging.getLogger("red.kirin_cogs.patron")

__red_end_user_data_statement__ = (
    "This cog stores supporters' Patreon and Buy Me a Coffee names, email addresses, pledge amounts and payment "
    "progress, and the Discord IDs they are linked to, to grant roles and currency. Red data-deletion requests "
    "remove these records."
)

GUILD_ID = 684360255798509578
HOST = "127.0.0.1"
WEBHOOK_PORT = 8014
WEBHOOK_PATH = "/bmc"
SYNC_SECONDS = 3600
PERIOD_SECONDS = 30 * 86400  # ponytail: fixed 30-day periods drift ~5 days/year from calendar billing
TIP_ROLE_SECONDS = PERIOD_SECONDS
STATE_KEYS = ("links", "patreon_members", "bmc_members", "bmc_tips")
SUBSCRIPTION_EVENTS = frozenset(
    {
        "membership.started",
        "membership.updated",
        "membership.cancelled",
        "membership.paused",
        "recurring_donation.started",
        "recurring_donation.updated",
        "recurring_donation.cancelled",
    }
)
TIP_EVENTS = frozenset({"donation.created", "donation.refunded"})

#: Rewards are whole currency units rounded half-up; yearly amounts become a monthly equivalent in cents first.
_CENT = Decimal("0.01")
_UNIT = Decimal("1")

State = dict[str, dict[str, Any]]


def calculate_reward(amount: Decimal) -> int:
    """3000 currency per unit of money, with bonuses: 5+: 5%, 10+: 10%, 20+: 15%, 40+: 20%."""
    bonus = Decimal("1.0")
    if amount >= 40:
        bonus = Decimal("1.20")
    elif amount >= 20:
        bonus = Decimal("1.15")
    elif amount >= 10:
        bonus = Decimal("1.10")
    elif amount >= 5:
        bonus = Decimal("1.05")
    return int((amount * 3000 * bonus).quantize(_UNIT, rounding=ROUND_HALF_UP))


def periods_due(anchor: float, now: float, limit: int | None) -> int:
    """How many 30-day periods have started since ``anchor`` (the first one starts at the anchor)."""
    if now < anchor:
        return 0
    due = int((now - anchor) // PERIOD_SECONDS) + 1
    return due if limit is None else min(due, limit)


def _decimal(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return Decimal(0)
    return amount if amount.is_finite() and amount > 0 else Decimal(0)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _records(bucket: Any) -> list[tuple[str, dict[str, Any]]]:
    return [(key, rec) for key, rec in bucket.items() if isinstance(rec, dict)] if isinstance(bucket, dict) else []


def merge_patreon(records: dict[str, Any], members: list[PatreonMember], now: float, *, baseline: bool) -> None:
    """Fold a fresh member list into stored records.

    A new paid charge starts a new run of periods (one for monthly, twelve for annual). With ``baseline`` the
    periods already started count as paid, so switching from the sheet does not pay this month twice.
    """
    seen = set()
    for member in members:
        seen.add(member.id)
        rec = records.get(member.id)
        if not isinstance(rec, dict):
            rec = records[member.id] = {"charge": None, "anchor": None, "periods": 1, "paid": 0}
        rec.update(
            name=member.name, email=member.email, discord_id=member.discord_id, status=member.status, cents=member.cents
        )
        charge = member.last_charge_date
        if member.last_charge_status == "Paid" and charge and charge != rec.get("charge"):
            try:
                anchor = datetime.fromisoformat(charge).timestamp()
            except ValueError:
                log.warning("Unreadable Patreon charge date %r for member %s", charge, member.id)
                continue
            rec.update(charge=charge, anchor=anchor, periods=member.cadence, paid=0)
            if baseline:
                rec["paid"] = periods_due(anchor, now, member.cadence)
    for member_id, rec in _records(records):
        if member_id not in seen:
            rec["status"] = None  # no longer in the campaign


def apply_bmc_event(state: State, event: dict[str, Any], now: float) -> str | None:
    """Fold one verified webhook event into state. Returns the changed bucket, or None if nothing changed."""
    event_type = str(event.get("type"))
    data = event["data"]
    if "id" not in data:
        return None
    created = _int(event.get("created")) or int(now)
    email = normalize_email(data.get("supporter_email"))
    details: dict[str, Any] = {
        "name": str(data.get("supporter_name") or ""),
        "email": email,
        "amount": str(_decimal(data.get("amount"))),
    }

    if event_type in SUBSCRIPTION_EVENTS:
        subs = state["bmc_members"]
        sub_id = f"{event_type.split('.')[0]}:{data['id']}"
        rec: dict[str, Any] | None = subs.get(sub_id)
        if not isinstance(rec, dict):
            rec = _adopt_manual(subs, email)
        if rec is None:
            started = _int(data.get("started_at")) or created
            # Seen first mid-membership (joined before the webhook existed): earlier periods are not back-paid.
            paid = 0 if event_type.endswith(".started") else periods_due(started, now, None)
            rec = {"anchor": started, "paid": paid, "updated": 0}
        if created < (_int(rec.get("updated")) or 0):
            return None  # an older event delivered late
        rec.update(
            details,
            status=data.get("status"),
            canceled=str(data.get("canceled")).lower() == "true",  # also set while active until the period ends
            duration="year" if data.get("duration_type") == "year" else "month",
            period_end=_int(data.get("current_period_end")) or 0,
            updated=created,
        )
        subs[sub_id] = rec
        return "bmc_members"

    if event_type in TIP_EVENTS:
        tips = state["bmc_tips"]
        tip: dict[str, Any] | None = tips.get(str(data["id"]))
        if not isinstance(tip, dict):
            tip = tips[str(data["id"])] = {"created": _int(data.get("created_at")) or created, "paid": 0}
        tip.update(details)
        if event_type == "donation.refunded" or data.get("status") == "refunded":
            tip["refunded"] = True
        return "bmc_tips"
    return None


def _adopt_manual(subs: dict[str, Any], email: str) -> dict[str, Any] | None:
    """Move a membership added with ``bmcadd`` under its webhook key so it is not paid twice."""
    for sub_id, rec in _records(subs):
        if rec.get("manual") and email and rec.get("email") == email:
            del subs[sub_id]
            rec.pop("manual")
            return rec
    return None


def add_bmc_member(state: State, email: str, user_id: int, amount: Decimal, duration: str, now: float) -> bool:
    """Record a membership that started before the webhook existed and link its email.

    The current period counts as paid. Adding the same email again corrects amount, duration and user. Returns
    False if the webhook already tracks an active membership for the email.
    """
    subs = state["bmc_members"]
    key = f"manual:{email}"
    if any(rid != key and rec.get("email") == email and rec.get("status") == "active" for rid, rec in _records(subs)):
        return False
    rec = subs.get(key)
    if not isinstance(rec, dict):
        rec = {"name": "", "anchor": now, "paid": 1, "updated": 0, "manual": True}
    rec.update(email=email, amount=str(amount), duration=duration, status="active", canceled=False, period_end=0)
    subs[key] = rec
    state["links"][email] = user_id
    return True


@dataclass(frozen=True)
class Entry:
    """One payment record, resolved to what the settle step needs."""

    bucket: str
    record_id: str
    user_id: int | None
    active: bool  # counts toward the Active role
    payable: bool
    anchor: float | None
    limit: int | None  # periods in the run; None = open-ended
    key: str
    reward: int
    label: str


def plan_entries(state: State, now: float) -> list[Entry]:
    """Every record that represents money paid, with its linked Discord ID, role status and reward."""
    links = state["links"]

    def user_id(rec: dict[str, Any]) -> int | None:
        # A staff link overrides the Discord account connected on Patreon.
        return _int(links.get(rec.get("email") or "")) or _int(rec.get("discord_id"))

    entries = []
    for rid, rec in _records(state["patreon_members"]):
        if not rec.get("charge"):
            continue  # free members and patrons never charged
        active = rec.get("status") == "active_patron"
        reward = calculate_reward(Decimal(_int(rec.get("cents")) or 0) / 100)
        entries.append(
            Entry(
                "patreon_members",
                rid,
                user_id(rec),
                active,
                active and reward > 0,
                rec.get("anchor"),
                _int(rec.get("periods")) or 1,
                f"patron:patreon:{rid}:{rec['charge']}",
                reward,
                "Patreon pledge",
            )
        )
    for rid, rec in _records(state["bmc_members"]):
        amount = _decimal(rec.get("amount"))
        if rec.get("duration") == "year":
            amount = (amount / 12).quantize(_CENT, rounding=ROUND_HALF_UP)
        paying = rec.get("status") == "active" and not rec.get("canceled")
        reward = calculate_reward(amount)
        active = paying or now < (_int(rec.get("period_end")) or 0)
        entries.append(
            Entry(
                "bmc_members",
                rid,
                user_id(rec),
                active,
                paying and reward > 0,
                rec.get("anchor"),
                None,
                f"patron:bmc:{rid}",
                reward,
                "Buy Me a Coffee membership",
            )
        )
    for rid, rec in _records(state["bmc_tips"]):
        created = _int(rec.get("created"))
        if created is None:
            continue
        refunded = bool(rec.get("refunded"))
        reward = calculate_reward(_decimal(rec.get("amount")))
        entries.append(
            Entry(
                "bmc_tips",
                rid,
                user_id(rec),
                not refunded and now < created + TIP_ROLE_SECONDS,
                not refunded and reward > 0,
                created,
                1,
                f"patron:bmc-tip:{rid}",
                reward,
                "Buy Me a Coffee tip",
            )
        )
    return entries


class Patron(commands.Cog):
    """Supporter roles and currency from Patreon and Buy Me a Coffee."""

    _runner: web.AppRunner
    _http: aiohttp.ClientSession

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9562341, force_registration=True)
        self.config.register_guild(
            schema_version=0,  # marker for migrations.py; 0 = legacy unmigrated record
            role_active=None,
            role_former=None,
            log_channel=None,
            links={},  # {email: discord_id}
            patreon_members={},  # {patreon member id: record}
            patreon_baselined=False,  # the first API sync counts current charges as already paid
            bmc_members={},  # {"membership:<id>" | "recurring_donation:<id>": record}
            bmc_tips={},  # {payment id: record}
            # Google Sheet era, kept so rolling back loses nothing.
            sheet_id=None,
            processed_charges={},
            annual_tracking={},
        )
        self.bg_task: asyncio.Task | None = None
        self.lock = asyncio.Lock()  # guards stored state
        self.sync_lock = asyncio.Lock()  # one Patreon poll at a time, so token refreshes never race
        self.patreon: PatreonClient

    async def cog_load(self) -> None:
        await migrate_guild_schemas(self.config)
        self._http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        self.patreon = PatreonClient(self.bot, self._http)
        self._runner = web.AppRunner(self.make_app(), access_log=None)
        await self._runner.setup()
        try:
            await web.TCPSite(self._runner, HOST, WEBHOOK_PORT).start()
        except OSError as exc:
            await self.cog_unload()
            raise CogLoadError(f"The webhook server could not listen on {HOST}:{WEBHOOK_PORT} ({exc}).") from exc
        self.bg_task = asyncio.create_task(self.sync_loop())
        self.bg_task.add_done_callback(self._on_bg_task_done)

    def _on_bg_task_done(self, task: asyncio.Task) -> None:
        """Retrieve and log background task exceptions instead of dropping them."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("Patron sync task failed: %s", exc, exc_info=exc)

    async def cog_unload(self) -> None:
        if self.bg_task:
            self.bg_task.cancel()
            await asyncio.gather(self.bg_task, return_exceptions=True)
            self.bg_task = None
        await self._runner.cleanup()
        await self._http.close()

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Remove links to this user and every payment record tied to them."""
        async with self.lock:
            for guild_id, data in (await self.config.all_guilds()).items():
                if not isinstance(data, dict):
                    continue
                group = self.config.guild_from_id(guild_id)
                links = _dict(data.get("links"))
                emails = {email for email, linked in links.items() if linked == user_id}
                for email in emails:
                    del links[email]
                await group.links.set(links)
                for key in ("patreon_members", "bmc_members", "bmc_tips"):
                    bucket = _dict(data.get(key))
                    for rid, rec in _records(bucket):
                        if rec.get("discord_id") == user_id or rec.get("email") in emails:
                            del bucket[rid]
                    await getattr(group, key).set(bucket)
                for key in ("processed_charges", "annual_tracking"):
                    legacy = data.get(key)
                    if isinstance(legacy, dict):
                        legacy.pop(str(user_id), None)
                        await getattr(group, key).set(legacy)

    # -- state ---------------------------------------------------------------------------------------------------

    async def _load(self) -> State:
        group = self.config.guild_from_id(GUILD_ID)
        state = {}
        for key in STATE_KEYS:
            state[key] = _dict(await getattr(group, key)())
        return state

    async def _save(self, state: State, key: str) -> None:
        await getattr(self.config.guild_from_id(GUILD_ID), key).set(state[key])

    # -- sync ----------------------------------------------------------------------------------------------------

    async def sync_loop(self) -> None:
        await self.bot.wait_until_ready()
        while True:
            try:
                await self.sync()
            except Exception:
                log.exception("Error in patron sync loop")
            await asyncio.sleep(SYNC_SECONDS)

    async def sync(self) -> str | None:
        """Poll Patreon, then pay what is due and sync roles. Returns the Patreon error, if any."""
        async with self.sync_lock:
            error = None
            members: list[PatreonMember] | None = None
            try:
                members = await self.patreon.members()  # outside self.lock so webhooks are not held up
            except (ApiError, aiohttp.ClientError, TimeoutError) as exc:
                error = str(exc) or type(exc).__name__
                log.warning("Patreon sync failed: %s", error)
            async with self.lock:
                if members is not None:
                    await self._merge_patreon(members)
                await self._settle()
            return error

    async def _merge_patreon(self, members: list[PatreonMember]) -> None:
        group = self.config.guild_from_id(GUILD_ID)
        state = await self._load()
        if not members:
            # Never baseline or mark everyone gone on an empty answer: the next real list would pay twice.
            log.warning("Patreon returned no members; keeping the stored ones.")
            return
        baseline = not await group.patreon_baselined()
        merge_patreon(state["patreon_members"], members, time.time(), baseline=baseline)
        await self._save(state, "patreon_members")
        if baseline:
            await group.patreon_baselined.set(True)
            log.info("Patreon baseline recorded for %d members; later charges pay out.", len(members))

    async def _settle(self) -> None:
        """Pay every period that is due and sync roles. The caller holds ``self.lock``."""
        guild = self.bot.get_guild(GUILD_ID)
        if guild is None:
            return
        state = await self._load()
        now = time.time()
        known: set[int] = set()
        active: set[int] = set()
        for entry in plan_entries(state, now):
            if entry.user_id is not None:
                known.add(entry.user_id)
                if entry.active:
                    active.add(entry.user_id)
            await self._pay_entry(guild, state, entry, now)
        await self._sync_roles(guild, known, active)

    async def _pay_entry(self, guild: discord.Guild, state: State, entry: Entry, now: float) -> None:
        rec = state[entry.bucket][entry.record_id]
        if not entry.payable or not isinstance(entry.anchor, int | float):
            return
        due = periods_due(entry.anchor, now, entry.limit)
        paid = _int(rec.get("paid")) or 0
        if paid >= due:
            return
        member = guild.get_member(entry.user_id) if entry.user_id else None
        if member is None:
            if entry.user_id is None and not rec.get("notified"):
                await self._log(
                    guild,
                    f"💸 Unlinked {entry.label} from **{escape(rec.get('name') or '?', formatting=True)}** "
                    f"(`{rec.get('email') or 'no email'}`). Its reward is held until someone runs "
                    f"`patronset link <user> {rec.get('email') or '<email>'}`.",
                )
                rec["notified"] = True
                await self._save(state, entry.bucket)
            return  # linked members who left are paid if they come back
        while paid < due:
            period = paid + 1
            reason = entry.label
            if entry.limit != 1:
                reason += f", month {period}" + (f"/{entry.limit}" if entry.limit else "")
            if not await self.award_currency(
                guild, member, entry.reward, reason, operation_key=f"{entry.key}:m{period}"
            ):
                return  # retried on the next sync
            paid = rec["paid"] = period
            await self._save(state, entry.bucket)

    async def _sync_roles(self, guild: discord.Guild, known: set[int], active: set[int]) -> None:
        """Active supporters get the Active role; anyone else who has paid before gets the Former role.

        Members the cog has no payment record for are left alone.
        """
        group = self.config.guild_from_id(GUILD_ID)
        role_active = guild.get_role(await group.role_active() or 0)
        role_former = guild.get_role(await group.role_former() or 0)
        if role_active is None or role_former is None:
            return
        me = guild.me
        if not me.guild_permissions.manage_roles or max(role_active, role_former) >= me.top_role:
            log.warning("Patron cannot manage the supporter roles: needs Manage Roles and a higher top role.")
            return
        for user_id in known:
            member = guild.get_member(user_id)
            if member is None:
                continue
            add, remove = (role_active, role_former) if user_id in active else (role_former, role_active)
            try:
                if remove in member.roles:
                    await member.remove_roles(remove, reason="Patron sync")
                if add not in member.roles:
                    await member.add_roles(add, reason="Patron sync")
            except discord.HTTPException as exc:
                log.warning("Could not update supporter roles for %s: %s", member.id, exc)

    async def _log(self, guild: discord.Guild, text: str) -> None:
        channel_id = await self.config.guild_from_id(GUILD_ID).log_channel()
        channel = guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException as exc:
                log.warning("Could not post to the patron log channel: %s", exc)

    async def award_currency(self, guild, member, amount, reason, *, operation_key: str) -> bool:
        """Award currency through Unicornia's idempotent operation API.

        Returns True only when the operation is durably settled (now or by a previous attempt), meaning callers may
        safely advance their own state.
        """
        unicornia = self.bot.get_cog("Unicornia")
        if not unicornia:
            log.warning("Unicornia cog not found. Cannot award currency.")
            return False
        try:
            outcome = await unicornia.apply_operation(
                key=operation_key,
                user_id=member.id,
                amount=amount,
                direction="credit",
                source="patron",
                guild_id=guild.id,
                reason=f"Supporter reward: {reason}",
            )
        except Exception:
            log.exception("Failed to award currency to %s", member.id)
            return False
        if outcome is None:
            log.error("Unicornia systems not ready; cannot award to %s", member.id)
            return False
        if outcome.state == "settled":
            log.info("Awarded %s to %s (%s)", amount, member.id, reason)
            await self._log(guild, f"🏆 **Supporter reward:** {amount} currency to {member.mention}.\n*{reason}*")
            return True
        if outcome.state == "duplicate":
            # Previously settled (e.g. crash after commit): safe to advance, but do not announce it twice.
            log.info("Patron operation %s already settled; advancing without re-award.", operation_key)
            return True
        log.error("Unexpected operation state %s awarding %s", outcome.state, member.id)
        return False

    # -- Buy Me a Coffee webhook ---------------------------------------------------------------------------------

    def make_app(self) -> web.Application:
        app = web.Application(client_max_size=256 * 1024)
        app.router.add_post(WEBHOOK_PATH, self.bmc_webhook)
        return app

    async def bmc_webhook(self, request: web.Request) -> web.Response:
        body = await request.read()
        secret = (await self.bot.get_shared_api_tokens("buymeacoffee")).get("webhook_secret")
        if not secret or not verify_bmc_signature(body, secret, request.headers.get("x-signature-sha256", "")):
            return web.Response(status=401)
        try:
            event = json.loads(body)
        except ValueError:
            return web.Response(status=400)
        if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
            return web.Response(status=400)
        if not event.get("live_mode"):
            log.info("Buy Me a Coffee test event %s received and ignored.", event.get("type"))
            return web.Response(text="test event ignored")
        event_type = str(event.get("type"))
        async with self.lock:
            state = await self._load()
            bucket = apply_bmc_event(state, event, time.time())
            if bucket is None:
                return web.Response(text="ignored")
            await self._save(state, bucket)
            try:
                await self._settle()
            except Exception:
                log.exception("Settling after a Buy Me a Coffee webhook failed; the hourly sync retries it.")
        if event_type.endswith(".refunded") and (guild := self.bot.get_guild(GUILD_ID)):
            data = event["data"]
            await self._log(
                guild,
                f"↩️ Buy Me a Coffee refund: {data.get('amount')} {data.get('currency') or ''} from "
                f"`{normalize_email(data.get('supporter_email')) or 'unknown'}`. Currency already awarded stays.",
            )
        return web.Response(text="ok")

    # -- commands ------------------------------------------------------------------------------------------------

    @commands.group()  # pyright: ignore[reportArgumentType]
    @checks.is_owner()
    async def patronset(self, ctx):
        """Settings for the Patron cog."""

    @patronset.command(name="roles")
    async def set_roles(self, ctx, active_role: discord.Role, former_role: discord.Role):
        """Set the Active and Former supporter roles."""
        if active_role.guild.id != GUILD_ID:
            return await ctx.send("Run this in the supporter server.")
        group = self.config.guild_from_id(GUILD_ID)
        await group.role_active.set(active_role.id)
        await group.role_former.set(former_role.id)
        await ctx.send(f"Roles set:\nActive: {active_role.name}\nFormer: {former_role.name}")

    @patronset.command(name="logchannel")
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel for rewards, unlinked payments and refunds."""
        if channel.guild.id != GUILD_ID:
            return await ctx.send("Run this in the supporter server.")
        await self.config.guild_from_id(GUILD_ID).log_channel.set(channel.id)
        await ctx.send(f"Log channel set to {channel.mention}.")

    @patronset.command(name="sync")
    async def manual_sync(self, ctx):
        """Poll Patreon now and pay anything due."""
        if self.sync_lock.locked():
            return await ctx.send("A sync is already in progress. Please wait.")
        async with ctx.typing():
            error = await self.sync()
        await ctx.send(f"Patreon sync failed: {error}" if error else "Sync complete.")

    @patronset.command(name="link")
    async def link(self, ctx, user: discord.User, email: str):
        """Link a Patreon/Buy Me a Coffee email to a Discord user and pay their held rewards."""
        email = normalize_email(email)
        async with self.lock:
            group = self.config.guild_from_id(GUILD_ID)
            links = _dict(await group.links())
            links[email] = user.id
            await group.links.set(links)
            await self._settle()
        await ctx.send(f"Linked `{email}` to {user.mention}.", allowed_mentions=discord.AllowedMentions.none())

    @patronset.command(name="unlink")
    async def unlink(self, ctx, email: str):
        """Remove an email link."""
        email = normalize_email(email)
        async with self.lock:
            group = self.config.guild_from_id(GUILD_ID)
            links = _dict(await group.links())
            removed = links.pop(email, None)
            await group.links.set(links)
        await ctx.send(f"Unlinked `{email}`." if removed else f"`{email}` was not linked.")

    @patronset.command(name="unlinked")
    async def list_unlinked(self, ctx):
        """List current supporters and held payments that are not linked to a Discord user."""
        state = await self._load()
        now = time.time()

        def waiting(entry: Entry) -> bool:
            if entry.active:
                return True
            if not entry.payable or not isinstance(entry.anchor, int | float):
                return False
            paid = _int(state[entry.bucket][entry.record_id].get("paid")) or 0
            return paid < periods_due(entry.anchor, now, entry.limit)

        entries = [entry for entry in plan_entries(state, now) if entry.user_id is None and waiting(entry)]
        if not entries:
            return await ctx.send("Every current supporter is linked.")
        lines = []
        for entry in entries:
            rec = state[entry.bucket][entry.record_id]
            name = escape(rec.get("name") or "?", formatting=True)
            lines.append(f"{entry.label}: **{name}** `{rec.get('email') or 'no email'}`")
        for page in pagify("\n".join(lines)):
            await ctx.send(page)

    @patronset.command(name="bmcadd")
    async def bmc_add(self, ctx, user: discord.User, email: str, amount: str, duration: str = "month"):
        """Add a Buy Me a Coffee member who joined before the webhook existed.

        `amount` is what they pay per month, or per year with `year`. Their current period counts as paid, so rewards
        start with the next one. Run it again for the same email to correct the amount, duration or user.
        """
        duration = duration.lower()
        value = _decimal(amount.strip("$€£ ").replace(",", "."))
        if duration not in ("month", "year") or value <= 0:
            return await ctx.send_help()
        email = normalize_email(email)
        async with self.lock:
            state = await self._load()
            if not add_bmc_member(state, email, user.id, value, duration, time.time()):
                return await ctx.send(f"`{email}` already has an active membership from the webhook.")
            await self._save(state, "bmc_members")
            await self._save(state, "links")
            await self._settle()
        await ctx.send(
            f"Added {user.mention}: {value} per {duration} (`{email}`). Rewards start with the next period.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @patronset.command(name="creds")
    async def creds(self, ctx):
        """How to set the Patreon and Buy Me a Coffee credentials."""
        await ctx.send(
            "**Patreon** (patreon.com/portal/registration/register-clients → your client):\n"
            "`[p]set api patreon access_token,<creator access token>,refresh_token,<creator refresh token>,"
            "client_id,<client id>,client_secret,<client secret>`\n"
            "Connect Patreon's Discord integration on your page so patrons' Discord IDs come through.\n\n"
            "**Buy Me a Coffee** (Integrations → Webhooks, events: memberships, recurring and one-time donations):\n"
            f"Webhook URL: `https://hooks.unicornia.net{WEBHOOK_PATH}` (Caddy → {HOST}:{WEBHOOK_PORT})\n"
            "`[p]set api buymeacoffee webhook_secret,<signing secret>`\n"
            "Members who joined before the webhook: `patronset bmcadd <user> <email> <amount> [month|year]`"
        )
