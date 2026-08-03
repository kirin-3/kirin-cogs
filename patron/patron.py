import asyncio
import logging
import re
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import discord
import gspread
from redbot.core import Config, checks, commands

from .migrations import migrate_guild_schemas

log = logging.getLogger("red.kirin_cogs.patron")

__red_end_user_data_statement__ = "This cog processes user IDs and usernames to sync roles and rewards. Data is stored in config only for tracking charge dates."

#: Money is parsed and calculated with Decimal; rewards are whole currency
#: units rounded half-up, and annual pledges are divided into a monthly
#: equivalent quantized to cents before tier calculation.
_CENT = Decimal("0.01")
_UNIT = Decimal("1")


class Patron(commands.Cog):
    """
    Syncs Discord roles and awards currency from a Google Sheet.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9562341, force_registration=True)

        default_guild = {
            "schema_version": 0,  # marker for migrations.py; 0 = legacy unmigrated record
            "sheet_id": None,
            "role_active": None,
            "role_former": None,
            "log_channel": None,
            "processed_charges": {},  # {username: last_charge_date_str}
            "annual_tracking": {},  # {username: {"anchor_date": str, "months_paid": int}}
        }

        self.config.register_guild(**default_guild)
        self.bg_task: asyncio.Task | None = None
        self.lock = asyncio.Lock()

    async def cog_load(self) -> None:
        await migrate_guild_schemas(self.config)
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

    async def red_delete_data_for_user(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, *, requester, user_id: int
    ) -> None:
        """Delete charge and annual-payment tracking keyed by Discord ID."""
        user_key = str(user_id)
        for guild_id, data in (await self.config.all_guilds()).items():
            if not isinstance(data, dict):
                continue
            processed = data.get("processed_charges", {})
            annual = data.get("annual_tracking", {})
            if not isinstance(processed, dict) or not isinstance(annual, dict):
                continue
            processed.pop(user_key, None)
            processed.pop(user_id, None)
            annual.pop(user_key, None)
            annual.pop(user_id, None)
            group = self.config.guild_from_id(guild_id)
            await group.processed_charges.set(processed)
            await group.annual_tracking.set(annual)

    async def sync_loop(self):
        """Background loop to periodically sync with Google Sheets."""
        await self.bot.wait_until_ready()
        while True:
            try:
                for guild in self.bot.guilds:
                    sheet_id = await self.config.guild(guild).sheet_id()
                    if sheet_id:
                        await self.process_sheet(guild, sheet_id)
            except Exception as e:
                log.error(f"Error in patron sync loop: {e}", exc_info=True)

            await asyncio.sleep(3600)  # Check every hour

    def get_creds_path(self):
        return Path(__file__).parent / "service_account.json"

    async def connect_to_sheet(self, sheet_id: str):
        """Connects to Google Sheet using service account."""
        creds_path = self.get_creds_path()
        if not creds_path.exists():
            return None, "service_account.json not found in cog folder."

        try:
            # We perform blocking I/O here, so we should run it in an executor if possible,
            # but gspread is synchronous. For simplicity in this loop, we'll run it directly
            # or wrap it if it blocks too long.
            def _connect():
                gc = gspread.service_account(filename=str(creds_path))
                sh = gc.open_by_key(sheet_id)
                # Assume data is in the first worksheet
                return sh.get_worksheet(0).get_all_records()

            return await self.bot.loop.run_in_executor(None, _connect), None
        except Exception as e:
            return None, str(e)

    async def process_sheet(self, guild: discord.Guild, sheet_id: str):
        """Main logic to process sheet data."""
        # Prevent race conditions between manual and auto sync
        if self.lock.locked():
            return

        async with self.lock:
            await self._process_sheet_logic(guild, sheet_id)

    @staticmethod
    def _resolve_member(guild: discord.Guild, identifier: str) -> tuple[discord.Member | None, bool]:
        """Resolve a sheet identifier to a guild member.

        Returns (member, used_legacy_username_match). Discord IDs are the
        canonical identity; a non-numeric identifier falls back to the legacy
        username match so historical rows keep working during the transition.
        """
        if identifier.isdigit():
            member = guild.get_member(int(identifier))
            if member is not None:
                return member, False
            return None, False
        # Legacy username matching (fragile; rows are logged for reconciliation)
        return discord.utils.get(guild.members, name=identifier), True

    def _charge_key(self, member: discord.Member, username: str, charges: dict) -> str:
        """Return the processed_charges key for reads: member ID preferred,
        falling back to the legacy username key if only that exists."""
        member_key = str(member.id)
        if member_key in charges:
            return member_key
        if username and username in charges:
            return username
        return member_key

    async def _process_sheet_logic(self, guild: discord.Guild, sheet_id: str):
        records, error = await self.connect_to_sheet(sheet_id)
        if error or records is None:
            log.error(f"Failed to connect to sheet for guild {guild.name}: {error}")
            return

        role_active_id = await self.config.guild(guild).role_active()
        role_former_id = await self.config.guild(guild).role_former()

        role_active = guild.get_role(role_active_id) if role_active_id else None
        role_former = guild.get_role(role_former_id) if role_former_id else None

        processed_charges = await self.config.guild(guild).processed_charges()
        if not isinstance(processed_charges, dict):
            processed_charges = {}
        annual_tracking = await self.config.guild(guild).annual_tracking()
        if not isinstance(annual_tracking, dict):
            annual_tracking = {}

        # Track sheet rows with "Active" status for reverse sync
        active_member_ids_in_sheet = set()
        active_usernames_in_sheet = set()
        legacy_rows = 0

        for i, row in enumerate(records):
            # Throttle to avoid rate limits
            if i > 0 and i % 5 == 0:
                await asyncio.sleep(2)

            username = ""
            try:
                identifier = str(row.get("Discord", "")).strip()
                if not identifier:
                    continue

                status = str(row.get("Patron Status", "")).lower()

                # Resolve member: Discord ID first, legacy username as fallback
                member, legacy_match = self._resolve_member(guild, identifier)
                if legacy_match:
                    legacy_rows += 1
                    log.info(
                        "Patron row matched by legacy username; migrate the sheet to Discord IDs for reconciliation."
                    )
                username = identifier if legacy_match else (member.name if member else identifier)

                if status == "active patron":
                    if member:
                        active_member_ids_in_sheet.add(member.id)
                    if legacy_match:
                        active_usernames_in_sheet.add(identifier)

                if not member:
                    # Unresolved rows (unknown ID or unmatched legacy username)
                    # are preserved for administrator reconciliation.
                    continue

                # --- Role Logic ---
                if role_active and role_former:
                    if status == "active patron":
                        # --- User is Active ---
                        # 1. Ensure Active Role
                        if role_active not in member.roles:
                            await member.add_roles(role_active, reason="Patron Sync: Active")
                        # 2. Ensure No Former Role
                        if role_former in member.roles:
                            await member.remove_roles(role_former, reason="Patron Sync: Active")
                    else:
                        # --- User is NOT Active (but is in sheet) ---
                        # If they have the Active role, they just lost it -> Move to Former
                        if role_active in member.roles:
                            await member.remove_roles(role_active, reason="Patron Sync: No longer Active")
                            if role_former not in member.roles:
                                await member.add_roles(role_former, reason="Patron Sync: No longer Active")

                        # If they are explicitly marked as Former/Declined, ensure they have Former role
                        elif status in ["declined patron", "former patron"]:
                            if role_former not in member.roles:
                                await member.add_roles(role_former, reason="Patron Sync: Status is Former/Declined")

                # --- Currency Logic ---
                # Only for Active patrons
                if status != "active patron":
                    continue

                last_charge_date = str(row.get("Last Charge Date", "")).strip()
                if not last_charge_date:
                    continue

                pledge_amount_str = str(row.get("Pledge Amount", "0"))
                charge_freq = str(row.get("Charge Frequency", "")).lower()
                is_annual = "annual" in charge_freq

                # Parse Amount (exact Decimal arithmetic)
                amount = self.parse_amount(pledge_amount_str)
                if amount <= 0:
                    continue

                # Calculate Monthly Equivalent for Reward
                # If Annual, the pledge amount in sheet is typically the Total Paid for the year.
                # We divide by 12 to get the "Tier Value" for rewards, quantized to cents.
                reward_base_amount = (amount / 12).quantize(_CENT, rounding=ROUND_HALF_UP) if is_annual else amount
                reward_value = self.calculate_reward(reward_base_amount)

                member_key = str(member.id)
                charge_key = self._charge_key(member, username, processed_charges)
                track_key = self._charge_key(member, username, annual_tracking)
                stored_charge_date = processed_charges.get(charge_key)

                if last_charge_date != stored_charge_date:
                    # NEW CHARGE DETECTED — payment identity is the idempotency key
                    operation_key = f"patron:{guild.id}:{member.id}:{last_charge_date}"
                    awarded = await self.award_currency(
                        guild, member, reward_value, "New Charge Processed", operation_key=operation_key
                    )
                    if not awarded:
                        # Unicornia did not settle: leave the charge unprocessed
                        # so the next sync retries the operation.
                        continue

                    # Advance only after a settled (or previously settled) result
                    processed_charges[member_key] = last_charge_date

                    # Setup Annual Tracking
                    if is_annual:
                        annual_tracking[member_key] = {
                            "anchor_date": datetime.utcnow().isoformat(),  # Use current time as anchor for bot distribution cycle
                            "months_paid": 1,
                            "last_award": datetime.utcnow().isoformat(),
                        }

                    # Save immediately to prevent double-awarding on crash
                    await self.config.guild(guild).processed_charges.set(processed_charges)
                    await self.config.guild(guild).annual_tracking.set(annual_tracking)

                else:
                    # SAME CHARGE - Check for Annual Recurring
                    if is_annual and track_key in annual_tracking:
                        track_data = annual_tracking[track_key]
                        months_paid = track_data.get("months_paid", 0)
                        anchor_iso = track_data.get("anchor_date")
                        last_award_iso = track_data.get("last_award")

                        if months_paid < 12 and anchor_iso:
                            anchor_date = datetime.fromisoformat(anchor_iso)
                            # Check if enough time has passed for next month's reward
                            # Simple logic: Anchor + (30 days * months_paid)
                            next_due = anchor_date + timedelta(days=30 * months_paid)

                            # Safety Check: Ensure we haven't awarded recently (last 25 days)
                            # This prevents double-processing if the loop restarts or logic glitches
                            safe_to_award = True
                            if last_award_iso:
                                last_award = datetime.fromisoformat(last_award_iso)
                                if (datetime.utcnow() - last_award) < timedelta(days=25):
                                    safe_to_award = False

                            if safe_to_award and datetime.utcnow() >= next_due:
                                month_number = months_paid + 1
                                operation_key = f"patron:{guild.id}:{member.id}:{last_charge_date}:m{month_number}"
                                awarded = await self.award_currency(
                                    guild,
                                    member,
                                    reward_value,
                                    f"Annual Pledge Month {month_number}/12",
                                    operation_key=operation_key,
                                )
                                if not awarded:
                                    continue

                                track_data["months_paid"] += 1
                                track_data["last_award"] = datetime.utcnow().isoformat()
                                if track_key != member_key:
                                    # Adopt tracking under the canonical member-ID key
                                    annual_tracking[member_key] = track_data

                                # Save immediately
                                await self.config.guild(guild).annual_tracking.set(annual_tracking)
            except Exception as e:
                log.error(f"Error processing row for {username}: {e}")

        if legacy_rows:
            log.warning(
                "Patron sync for guild %s resolved %d row(s) by legacy username; "
                "update the sheet with Discord IDs and review `[p]patronset unreconciled`.",
                guild.name,
                legacy_rows,
            )

        # --- Reverse Sync (Cleanup) ---
        # If a user has the Active Role but is NOT in the "Active" list from the sheet, downgrade them.
        if role_active and role_former:
            for i, member in enumerate(role_active.members):
                # Throttle
                if i > 0 and i % 5 == 0:
                    await asyncio.sleep(2)

                try:
                    # Discord IDs are authoritative; legacy usernames still count
                    # so unresolved legacy rows are not downgraded by accident.
                    if member.id not in active_member_ids_in_sheet and member.name not in active_usernames_in_sheet:
                        log.info(f"Downgrading {member.name} (Not found in Active list)")
                        await member.remove_roles(role_active, reason="Patron Sync: Not in Active list")
                        await member.add_roles(role_former, reason="Patron Sync: Not in Active list")
                except Exception as e:
                    log.error(f"Error in reverse sync for {member.name}: {e}")

    def parse_amount(self, amount_str: str) -> Decimal:
        """Parse a localized monetary string into an exact Decimal.

        Handles "$5.00", "€5,00", "1,000.00" (US) and "1.000,00" (European)
        without ever using binary floating-point arithmetic.
        """
        # 1. Remove currency symbols and spaces
        clean = re.sub(r"[^\d.,]", "", amount_str)
        if not clean:
            return Decimal("0")

        # 2. Handle specific European case: "1.234,56" -> "1234.56"
        # If both . and , exist:
        if "." in clean and "," in clean:
            # Assume the last one is the decimal separator
            last_dot = clean.rfind(".")
            last_comma = clean.rfind(",")

            if last_comma > last_dot:
                # Comma is decimal (European: 1.000,00)
                clean = clean.replace(".", "")  # Remove thousands sep
                clean = clean.replace(",", ".")  # Replace decimal with dot
            else:
                # Dot is decimal (US: 1,000.00)
                clean = clean.replace(",", "")  # Remove thousands sep

        # 3. If only comma exists: "5,00" or "1,000"
        elif "," in clean:
            # For "5,00" -> 5.00
            clean = clean.replace(",", ".")

        try:
            return Decimal(clean)
        except InvalidOperation:
            return Decimal("0")

    def calculate_reward(self, amount: Decimal) -> int:
        """
        Calculates reward based on rules:
        - 3000 per 1 unit (15000 per 5).
        - Bonus: 5+: 5%, 10+: 10%, 20+: 15%, 40+: 20%

        The result is rounded half-up to whole currency units.
        """
        base = amount * 3000

        bonus = Decimal("1.0")
        if amount >= 40:
            bonus = Decimal("1.20")
        elif amount >= 20:
            bonus = Decimal("1.15")
        elif amount >= 10:
            bonus = Decimal("1.10")
        elif amount >= 5:
            bonus = Decimal("1.05")

        return int((base * bonus).quantize(_UNIT, rounding=ROUND_HALF_UP))

    async def award_currency(self, guild, member, amount, reason, *, operation_key: str) -> bool:
        """Award currency through Unicornia's idempotent operation API.

        Returns True only when the operation is durably settled (now or by a
        previous attempt), meaning callers may safely advance their own state.
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
                reason=f"Patreon: {reason}",
            )
            if outcome is None:
                log.error("Unicornia systems not ready; cannot award to %s", member.name)
                return False

            if outcome.state == "settled":
                log.info(f"Awarded {amount} to {member.name} ({reason})")

                # Log to channel if configured
                log_channel_id = await self.config.guild(guild).log_channel()
                if log_channel_id:
                    channel = guild.get_channel(log_channel_id)
                    if channel:
                        await channel.send(
                            f"🏆 **Patreon Reward:** Awarded {amount} currency to {member.mention}.\n*Reason: {reason}*"
                        )
                return True

            if outcome.state == "duplicate":
                # Previously settled (e.g. crash after commit): safe to advance,
                # but do not announce the award a second time.
                log.info("Patron operation %s already settled; advancing without re-award.", operation_key)
                return True

            log.error("Unexpected operation state %s awarding %s", outcome.state, member.name)
            return False
        except Exception as e:
            log.error(f"Failed to award currency to {member.name}: {e}")
            return False

    @commands.group()  # pyright: ignore[reportArgumentType]
    @checks.is_owner()
    async def patronset(self, ctx):
        """Settings for Patron cog."""
        pass

    @patronset.command(name="setup")
    async def set_sheet_id(self, ctx, sheet_id: str):
        """Set the Google Sheet ID."""
        await self.config.guild(ctx.guild).sheet_id.set(sheet_id)
        await ctx.send(f"Sheet ID set to `{sheet_id}`.")

    @patronset.command(name="roles")
    async def set_roles(self, ctx, active_role: discord.Role, former_role: discord.Role):
        """Set the Active and Former Patron roles."""
        await self.config.guild(ctx.guild).role_active.set(active_role.id)
        await self.config.guild(ctx.guild).role_former.set(former_role.id)
        await ctx.send(f"Roles set:\nActive: {active_role.name}\nFormer: {former_role.name}")

    @patronset.command(name="logchannel")
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        """Set channel for reward logs."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Log channel set to {channel.mention}.")

    @patronset.command(name="sync")
    async def manual_sync(self, ctx):
        """Manually trigger a sync."""
        if self.lock.locked():
            return await ctx.send("A sync is already in progress. Please wait.")

        await ctx.send("Starting sync process...")
        sheet_id = await self.config.guild(ctx.guild).sheet_id()
        if not sheet_id:
            return await ctx.send("Sheet ID not set.")

        async with ctx.typing():
            await self.process_sheet(ctx.guild, sheet_id)
        await ctx.send("Sync complete.")

    @patronset.command(name="unreconciled")
    async def list_unreconciled(self, ctx):
        """List legacy username-keyed charge records awaiting reconciliation.

        New payments are tracked by Discord ID. Entries shown here predate
        that policy and are preserved so an administrator can map them to
        Discord IDs manually (or remove them once resolved).
        """
        processed_charges = await self.config.guild(ctx.guild).processed_charges()
        if not isinstance(processed_charges, dict):
            processed_charges = {}

        legacy_entries = [(key, value) for key, value in processed_charges.items() if not str(key).isdigit()]
        if not legacy_entries:
            return await ctx.send("No unreconciled legacy records. All charges are keyed by Discord ID.")

        lines = [f"`{name}` — last processed charge: {date}" for name, date in legacy_entries[:20]]
        summary = f"**{len(legacy_entries)} legacy username-keyed record(s):**\n" + "\n".join(lines)
        if len(legacy_entries) > 20:
            summary += f"\n… and {len(legacy_entries) - 20} more."
        await ctx.send(summary)

    @patronset.command(name="creds")
    async def upload_creds(self, ctx):
        """Instructions to upload credentials."""
        msg = (
            "To set up credentials:\n"
            "1. Rename your JSON key file to `service_account.json`\n"
            f"2. Upload it to this folder: `{self.get_creds_path().parent}`\n"
            "   (You need to do this via file manager, I cannot accept file uploads via command for security/complexity reasons currently)."
        )
        await ctx.send(msg)
