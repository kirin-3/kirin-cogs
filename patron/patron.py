import discord
import asyncio
import logging
import json
import gspread
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Union, Any

from redbot.core import commands, Config, checks
from redbot.core.utils.chat_formatting import box, pagify

log = logging.getLogger("red.kirin_cogs.patron")

class Patron(commands.Cog):
    """
    Syncs Discord roles and awards currency from a Google Sheet.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9562341, force_registration=True)
        
        default_guild = {
            "sheet_id": None,
            "role_active": None,
            "role_former": None,
            "log_channel": None,
            "processed_charges": {},  # {username: last_charge_date_str}
            "annual_tracking": {},    # {username: {"anchor_date": str, "months_paid": int}}
        }
        
        self.config.register_guild(**default_guild)
        self.bg_task = self.bot.loop.create_task(self.sync_loop())
        self.lock = asyncio.Lock()
        
    def cog_unload(self):
        if self.bg_task:
            self.bg_task.cancel()
            
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

    async def _process_sheet_logic(self, guild: discord.Guild, sheet_id: str):
        records, error = await self.connect_to_sheet(sheet_id)
        if error:
            log.error(f"Failed to connect to sheet for guild {guild.name}: {error}")
            return

        role_active_id = await self.config.guild(guild).role_active()
        role_former_id = await self.config.guild(guild).role_former()
        
        role_active = guild.get_role(role_active_id) if role_active_id else None
        role_former = guild.get_role(role_former_id) if role_former_id else None

        processed_charges = await self.config.guild(guild).processed_charges()
        annual_tracking = await self.config.guild(guild).annual_tracking()
        
        # Track changes to save config later
        config_changed = False
        
        # Track usernames found in sheet with "Active" status
        active_usernames_in_sheet = set()

        for row in records:
            try:
                username = str(row.get("Discord", "")).strip()
                if not username:
                    continue

                status = str(row.get("Patron Status", "")).lower()
                if status == "active patron":
                    active_usernames_in_sheet.add(username)

                # Resolve User
                # Try to find by name or discriminator
                # This is "best effort" mapping by name
                member = discord.utils.get(guild.members, name=username)
                # Try global lookup if not found (though we need guild member for roles)
                if not member:
                    # Try partial match or discriminator logic if needed, but keeping it strict for now
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
                
                # Parse Amount
                amount = self.parse_amount(pledge_amount_str)
                if amount <= 0:
                    continue

                # Calculate Monthly Equivalent for Reward
                # If Annual, the pledge amount in sheet is typically the Total Paid for the year.
                # We divide by 12 to get the "Tier Value" for rewards.
                reward_base_amount = amount / 12 if is_annual else amount
                reward_value = self.calculate_reward(reward_base_amount)

                # Check for New Charge
                stored_charge_date = processed_charges.get(username)
                
                if last_charge_date != stored_charge_date:
                    # NEW CHARGE DETECTED
                    await self.award_currency(guild, member, reward_value, "New Charge Processed")
                    
                    processed_charges[username] = last_charge_date
                    config_changed = True
                    
                    # Setup Annual Tracking
                    if is_annual:
                        annual_tracking[username] = {
                            "anchor_date": datetime.utcnow().isoformat(), # Use current time as anchor for bot distribution cycle
                            "months_paid": 1
                        }
                
                else:
                    # SAME CHARGE - Check for Annual Recurring
                    if is_annual and username in annual_tracking:
                        track_data = annual_tracking[username]
                        months_paid = track_data.get("months_paid", 0)
                        anchor_iso = track_data.get("anchor_date")
                        
                        if months_paid < 12 and anchor_iso:
                            anchor_date = datetime.fromisoformat(anchor_iso)
                            # Check if enough time has passed for next month's reward
                            # Simple logic: Anchor + (30 days * months_paid)
                            next_due = anchor_date + timedelta(days=30 * months_paid)
                            
                            if datetime.utcnow() >= next_due:
                                await self.award_currency(guild, member, reward_value, f"Annual Pledge Month {months_paid + 1}/12")
                                track_data["months_paid"] += 1
                                config_changed = True
            except Exception as e:
                log.error(f"Error processing row for {username}: {e}")

        # --- Reverse Sync (Cleanup) ---
        # If a user has the Active Role but is NOT in the "Active" list from the sheet, downgrade them.
        if role_active and role_former:
            for member in role_active.members:
                try:
                    # Warning: Matching by name is fragile, but it's the only link we have.
                    # If the user changed their name, they might be downgraded accidentally.
                    if member.name not in active_usernames_in_sheet:
                        log.info(f"Downgrading {member.name} (Not found in Active list)")
                        await member.remove_roles(role_active, reason="Patron Sync: Not in Active list")
                        await member.add_roles(role_former, reason="Patron Sync: Not in Active list")
                except Exception as e:
                    log.error(f"Error in reverse sync for {member.name}: {e}")

        if config_changed:
            await self.config.guild(guild).processed_charges.set(processed_charges)
            await self.config.guild(guild).annual_tracking.set(annual_tracking)

    def parse_amount(self, amount_str: str) -> float:
        """Strips currency symbols and returns float. Handles '1.000,00' and '1,000.00'."""
        # 1. Remove currency symbols and spaces
        clean = re.sub(r'[^\d.,]', '', amount_str)
        if not clean:
            return 0.0
            
        # 2. Handle specific European case: "1.234,56" -> "1234.56"
        # If both . and , exist:
        if '.' in clean and ',' in clean:
            # Assume the last one is the decimal separator
            last_dot = clean.rfind('.')
            last_comma = clean.rfind(',')
            
            if last_comma > last_dot:
                # Comma is decimal (European: 1.000,00)
                clean = clean.replace('.', '') # Remove thousands sep
                clean = clean.replace(',', '.') # Replace decimal with dot
            else:
                # Dot is decimal (US: 1,000.00)
                clean = clean.replace(',', '') # Remove thousands sep
                
        # 3. If only comma exists: "5,00" or "1,000"
        elif ',' in clean:
            # For "5,00" -> 5.00
            clean = clean.replace(',', '.')
            
        try:
            return float(clean)
        except ValueError:
            return 0.0

    def calculate_reward(self, amount: float) -> int:
        """
        Calculates reward based on rules:
        - 3000 per 1 unit (15000 per 5).
        - Bonus: 5+: 5%, 10+: 10%, 20+: 15%, 40+: 20%
        """
        base = amount * 3000
        
        bonus = 1.0
        if amount >= 40:
            bonus = 1.20
        elif amount >= 20:
            bonus = 1.15
        elif amount >= 10:
            bonus = 1.10
        elif amount >= 5:
            bonus = 1.05
            
        return int(base * bonus)

    async def award_currency(self, guild, member, amount, reason):
        """Awards currency using Unicornia cog."""
        unicornia = self.bot.get_cog("Unicornia")
        if not unicornia:
            log.warning("Unicornia cog not found. Cannot award currency.")
            return

        try:
            success = await unicornia.add_balance(member.id, amount, reason=f"Patreon: {reason}", source="patron")
            if success:
                log.info(f"Awarded {amount} to {member.name} ({reason})")
                
                # Log to channel if configured
                log_channel_id = await self.config.guild(guild).log_channel()
                if log_channel_id:
                    channel = guild.get_channel(log_channel_id)
                    if channel:
                        await channel.send(f"🏆 **Patreon Reward:** Awarded {amount} currency to {member.mention}.\n*Reason: {reason}*")
        except Exception as e:
            log.error(f"Failed to award currency to {member.name}: {e}")

    @commands.group()
    @checks.is_owner()
    async def patreonset(self, ctx):
        """Settings for Patron cog."""
        pass
        
    @patreonset.command(name="setup")
    async def set_sheet_id(self, ctx, sheet_id: str):
        """Set the Google Sheet ID."""
        await self.config.guild(ctx.guild).sheet_id.set(sheet_id)
        await ctx.send(f"Sheet ID set to `{sheet_id}`.")
        
    @patreonset.command(name="roles")
    async def set_roles(self, ctx, active_role: discord.Role, former_role: discord.Role):
        """Set the Active and Former Patron roles."""
        await self.config.guild(ctx.guild).role_active.set(active_role.id)
        await self.config.guild(ctx.guild).role_former.set(former_role.id)
        await ctx.send(f"Roles set:\nActive: {active_role.name}\nFormer: {former_role.name}")
        
    @patreonset.command(name="logchannel")
    async def set_log_channel(self, ctx, channel: discord.TextChannel):
        """Set channel for reward logs."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Log channel set to {channel.mention}.")
        
    @patreonset.command(name="sync")
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
        
    @patreonset.command(name="creds")
    async def upload_creds(self, ctx):
        """Instructions to upload credentials."""
        msg = (
            "To set up credentials:\n"
            "1. Rename your JSON key file to `service_account.json`\n"
            f"2. Upload it to this folder: `{self.get_creds_path().parent}`\n"
            "   (You need to do this via file manager, I cannot accept file uploads via command for security/complexity reasons currently)."
        )
        await ctx.send(msg)
