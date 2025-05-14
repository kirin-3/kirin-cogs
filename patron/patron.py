import discord
import asyncio
import aiohttp
import json
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Union, Any

from redbot.core import commands, Config, checks
from redbot.core.utils.chat_formatting import box, humanize_list, pagify
from redbot.core.utils.menus import DEFAULT_CONTROLS, menu

__red_end_user_data_statement__ = "This cog stores Discord user IDs linked to their Patreon donation data."

class Patron(commands.Cog):
    """
    Send messages based on Patreon donation amounts
    
    Connects to Patreon API to fetch donation data and sends award messages.
    """

    # Hardcoded channel ID for all donation messages
    AWARD_CHANNEL_ID = 887073219788537876

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9562341, force_registration=True)
        self.session = aiohttp.ClientSession()
        
        default_guild = {
            "api_settings": {
                "client_id": None,
                "client_secret": None,
                "creator_access_token": None,
                "creator_refresh_token": None,
                "campaign_id": None,
                "webhook_secret": None,
            },
            "award_channel": None,  # Kept for backward compatibility but not used
            "last_check": None,
            "patreon_discord_connections": {},  # patreon_id: discord_id
            "processed_donations": {},  # member_id: last_charge_date processed
            "message_format": ".award {amount} {discord_user}",
            "min_donation_amount": 1.0, # Minimum donation amount to trigger award
            "process_monthly": True, # Whether to process monthly recurring donations
        }
        
        self.config.register_guild(**default_guild)
        self.bg_task = self.bot.loop.create_task(self.check_patrons_loop())
        
    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())
        if self.bg_task:
            self.bg_task.cancel()
        
    async def check_patrons_loop(self):
        """Background loop to periodically check for new patrons and donations."""
        await self.bot.wait_until_ready()
        while True:
            for guild in self.bot.guilds:
                try:
                    settings = await self.config.guild(guild).api_settings()
                    if all([settings["client_id"], settings["client_secret"], 
                           settings["creator_access_token"], settings["campaign_id"]]):
                        await self.check_and_process_donations(guild)
                except Exception as e:
                    self.bot.logger.error(f"Error in patron check loop: {e}", exc_info=True)
            await asyncio.sleep(3600)  # Check once an hour
        
    @commands.group(name="patreonset")
    @commands.guild_only()
    @checks.is_owner()
    async def patreonset(self, ctx):
        """Configure Patreon API integration"""
        pass
    
    @patreonset.command(name="clientid")
    async def set_client_id(self, ctx, client_id: str):
        """Set your Patreon API Client ID"""
        async with self.config.guild(ctx.guild).api_settings() as settings:
            settings["client_id"] = client_id
        await ctx.send("Patreon Client ID has been set.")
        await ctx.message.delete()
    
    @patreonset.command(name="clientsecret")
    async def set_client_secret(self, ctx, client_secret: str):
        """Set your Patreon API Client Secret"""
        async with self.config.guild(ctx.guild).api_settings() as settings:
            settings["client_secret"] = client_secret
        await ctx.send("Patreon Client Secret has been set.")
        await ctx.message.delete()
    
    @patreonset.command(name="accesstoken")
    async def set_access_token(self, ctx, access_token: str):
        """Set your Patreon Creator Access Token"""
        async with self.config.guild(ctx.guild).api_settings() as settings:
            settings["creator_access_token"] = access_token
        await ctx.send("Patreon Creator Access Token has been set.")
        await ctx.message.delete()
    
    @patreonset.command(name="refreshtoken")
    async def set_refresh_token(self, ctx, refresh_token: str):
        """Set your Patreon Creator Refresh Token"""
        async with self.config.guild(ctx.guild).api_settings() as settings:
            settings["creator_refresh_token"] = refresh_token
        await ctx.send("Patreon Creator Refresh Token has been set.")
        await ctx.message.delete()
    
    @patreonset.command(name="campaignid")
    async def set_campaign_id(self, ctx, campaign_id: str):
        """Set your Patreon Campaign ID"""
        async with self.config.guild(ctx.guild).api_settings() as settings:
            settings["campaign_id"] = campaign_id
        await ctx.send("Patreon Campaign ID has been set.")
    
    @patreonset.command(name="messageformat")
    async def set_message_format(self, ctx, *, format_str: str):
        """
        Set the format for award messages
        
        Available placeholders:
        {amount} - The calculated award amount (3000 per 1 EUR/USD donated with tier bonuses)
        {discord_user} - The Discord user mention
        {patron_name} - The patron's full name from Patreon
        {recurring} - "new" for first time donors, "monthly" for recurring donations
        
        Bonus tiers:
        - 5-9.99 EUR: 5% bonus
        - 10-19.99 EUR: 10% bonus
        - 20-39.99 EUR: 15% bonus
        - 40+ EUR: 20% bonus
        
        Example: .award {amount} {discord_user}
        """
        await self.config.guild(ctx.guild).message_format.set(format_str)
        await ctx.send(f"Award message format set to: {format_str}")
    
    @patreonset.command(name="minamount")
    async def set_min_amount(self, ctx, amount: float):
        """Set the minimum donation amount that triggers an award message"""
        await self.config.guild(ctx.guild).min_donation_amount.set(amount)
        await ctx.send(f"Minimum donation amount set to ${amount:.2f}")
    
    @patreonset.command(name="monthly")
    async def set_monthly_processing(self, ctx, enabled: bool = True):
        """
        Enable or disable processing of monthly recurring donations
        
        Set to True to send award messages for recurring monthly donations.
        Set to False to only send messages for first-time donations.
        """
        await self.config.guild(ctx.guild).process_monthly.set(enabled)
        if enabled:
            await ctx.send("Monthly recurring donation processing is now enabled.")
        else:
            await ctx.send("Monthly recurring donation processing is now disabled. Only first-time donations will trigger messages.")
    
    @patreonset.command(name="status")
    async def show_status(self, ctx):
        """Show current Patreon API configuration status"""
        settings = await self.config.guild(ctx.guild).api_settings()
        message_format = await self.config.guild(ctx.guild).message_format()
        min_amount = await self.config.guild(ctx.guild).min_donation_amount()
        process_monthly = await self.config.guild(ctx.guild).process_monthly()
        last_check = await self.config.guild(ctx.guild).last_check()
        
        # Create API status markers
        api_statuses = {
            "Client ID": "✅" if settings["client_id"] else "❌",
            "Client Secret": "✅" if settings["client_secret"] else "❌",
            "Access Token": "✅" if settings["creator_access_token"] else "❌", 
            "Refresh Token": "✅" if settings["creator_refresh_token"] else "❌",
            "Campaign ID": "✅" if settings["campaign_id"] else "❌"
        }
        
        status_text = "\n".join([f"{name}: {status}" for name, status in api_statuses.items()])
        
        embed = discord.Embed(
            title="Patreon Integration Status",
            color=discord.Color.blue(),
            description=f"**API Configuration:**\n{status_text}"
        )
        
        # Find the hardcoded award channel
        award_channel = self.bot.get_channel(self.AWARD_CHANNEL_ID)
        channel_info = f"<#{self.AWARD_CHANNEL_ID}>" if award_channel else f"Channel with ID {self.AWARD_CHANNEL_ID} not found"
        
        embed.add_field(name="Award Channel", value=channel_info, inline=False)
        embed.add_field(name="Message Format", value=f"`{message_format}`", inline=False)
        embed.add_field(name="Minimum Amount", value=f"${min_amount:.2f}", inline=True)
        embed.add_field(name="Process Monthly", value="✅" if process_monthly else "❌", inline=True)
        
        if last_check:
            last_check_time = datetime.fromisoformat(last_check)
            time_since = datetime.utcnow() - last_check_time
            embed.add_field(name="Last API Check", value=f"{time_since.days}d {time_since.seconds // 3600}h ago", inline=True)
        
        await ctx.send(embed=embed)
    
    @patreonset.command(name="checkconnections")
    async def check_connections(self, ctx):
        """
        Check Patreon-Discord connections in the system
        
        This shows which Patreon users are connected to Discord accounts
        """
        connections = await self.config.guild(ctx.guild).patreon_discord_connections()
        
        if not connections:
            return await ctx.send("No Patreon-Discord connections found.")
        
        lines = []
        for patreon_id, discord_id in connections.items():
            discord_user = self.bot.get_user(int(discord_id))
            discord_name = f"@{discord_user}" if discord_user else f"Unknown User ({discord_id})"
            lines.append(f"Patreon ID: {patreon_id} → Discord: {discord_name}")
        
        pages = []
        for page in pagify("\n".join(lines), page_length=1000):
            pages.append(box(page))
        
        if len(pages) == 1:
            await ctx.send(pages[0])
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)
    
    @patreonset.command(name="manualconnect")
    async def manual_connect(self, ctx, patreon_id: str, discord_user: discord.Member):
        """Manually connect a Patreon user ID to a Discord user"""
        async with self.config.guild(ctx.guild).patreon_discord_connections() as connections:
            connections[patreon_id] = str(discord_user.id)
        
        await ctx.send(f"Connected Patreon ID `{patreon_id}` to Discord user {discord_user.mention}")
    
    @patreonset.command(name="checkpatrons")
    async def manual_check_patrons(self, ctx):
        """Manually trigger a check for new patrons and donations"""
        async with ctx.typing():
            result = await self.check_and_process_donations(ctx.guild)
            
            if isinstance(result, str):
                await ctx.send(f"Error checking patrons: {result}")
            else:
                await ctx.send(f"Patron check complete! Processed {result['new']} new donations and {result['recurring']} recurring donations.")
    
    @patreonset.command(name="refreshpatreontoken")
    async def refresh_patreon_token(self, ctx):
        """Manually refresh your Patreon access token"""
        async with ctx.typing():
            settings = await self.config.guild(ctx.guild).api_settings()
            
            if not all([settings["client_id"], settings["client_secret"], settings["creator_refresh_token"]]):
                return await ctx.send("Missing required Patreon API credentials. Please set client ID, client secret, and refresh token.")
            
            result = await self.refresh_access_token(ctx.guild)
            
            if isinstance(result, str):
                await ctx.send(f"Error refreshing token: {result}")
            else:
                await ctx.send("Successfully refreshed Patreon access token!")
    
    @patreonset.command(name="cleartransactions")
    async def clear_processed_transactions(self, ctx, confirm: bool = False):
        """
        Clear all processed donation records to reprocess them
        
        Use this if you want to resend all award messages. 
        This will trigger messages for ALL patrons on the next check.
        
        Set confirm to True to confirm this action.
        """
        if not confirm:
            return await ctx.send("This will clear ALL processed donation records and resend messages for every patron. "
                                 "If you're sure, run the command again with `confirm=True`.")
        
        await self.config.guild(ctx.guild).processed_donations.set({})
        await ctx.send("All processed donation records have been cleared. "
                      "The next check will process all patrons as if they were new donors.")
    
    @patreonset.command(name="listpatrons")
    @checks.is_owner()
    async def list_patrons(self, ctx):
        """
        List Discord usernames of current patrons without pinging them
        
        This command fetches current patrons from Patreon and displays their
        Discord usernames if a connection exists.
        """
        async with ctx.typing():
            settings = await self.config.guild(ctx.guild).api_settings()
            
            if not all([settings["creator_access_token"], settings["campaign_id"]]):
                return await ctx.send("Missing required API credentials. Please set up the Patreon API integration first.")
            
            # Get members (patrons) from Patreon API
            members = await self.get_campaign_members(ctx.guild)
            
            if isinstance(members, str):
                return await ctx.send(f"Error fetching patrons: {members}")
            
            # Get Discord-Patreon connections
            connections = await self.config.guild(ctx.guild).patreon_discord_connections()
            
            # Track patrons with Discord connections
            patrons_with_discord = []
            
            for member in members:
                try:
                    # Extract member info
                    attributes = member.get("attributes", {})
                    relationships = member.get("relationships", {})
                    
                    # Skip patrons with no active pledge
                    amount_cents = attributes.get("currently_entitled_amount_cents", 0)
                    if not amount_cents:
                        continue
                    
                    # Get patron status
                    patron_status = attributes.get("patron_status")
                    if patron_status not in ["active_patron", "pending_payment"]:
                        continue
                    
                    # Get user relationship
                    user_relationship = relationships.get("user", {}).get("data", {})
                    user_id = user_relationship.get("id")
                    
                    if not user_id:
                        continue
                    
                    # Get patron name
                    patron_name = attributes.get("full_name", "Unknown Patron")
                    amount_dollars = amount_cents / 100
                    
                    # Try to get Discord connection from social connections
                    discord_id = None
                    discord_username = None
                    
                    # Check included user data
                    for included in member.get("included", []):
                        if included.get("type") == "user" and included.get("id") == user_id:
                            user_data = included
                            user_attributes = user_data.get("attributes", {})
                            
                            # Check for Discord connection in social connections
                            social_connections = user_attributes.get("social_connections", {})
                            discord_connection = social_connections.get("discord")
                            
                            if discord_connection:
                                discord_id = discord_connection.get("user_id")
                            break
                    
                    # If no Discord ID from social connections, check our stored mappings
                    if not discord_id and user_id in connections:
                        discord_id = connections[user_id]
                    
                    # Skip if we don't have a Discord ID
                    if not discord_id:
                        continue
                    
                    # Get Discord user
                    try:
                        discord_user = await ctx.guild.fetch_member(int(discord_id))
                        discord_username = str(discord_user)  # Get the username without pinging
                    except (discord.NotFound, discord.HTTPException):
                        # Try to get the user from the bot's cache
                        discord_user = self.bot.get_user(int(discord_id))
                        if discord_user:
                            discord_username = str(discord_user)
                        else:
                            discord_username = f"Unknown (ID: {discord_id})"
                    
                    # Add to our list
                    patrons_with_discord.append({
                        "name": patron_name,
                        "discord": discord_username,
                        "amount": amount_dollars
                    })
                    
                except Exception as e:
                    self.bot.logger.error(f"Error processing member {member.get('id')}: {e}", exc_info=True)
            
            if not patrons_with_discord:
                return await ctx.send("No patrons with Discord connections found.")
            
            # Sort by donation amount (highest first)
            patrons_with_discord.sort(key=lambda x: x["amount"], reverse=True)
            
            # Build embed for display
            embed = discord.Embed(
                title="Current Patrons with Discord Accounts",
                color=discord.Color.gold(),
                description=f"Found {len(patrons_with_discord)} patrons with Discord connections"
            )
            
            # Add patrons to embed
            patron_lines = []
            for patron in patrons_with_discord:
                patron_lines.append(f"**{patron['discord']}** - ${patron['amount']:.2f}/month")
            
            # Split into fields if there are many patrons
            chunks = [patron_lines[i:i+10] for i in range(0, len(patron_lines), 10)]
            
            for i, chunk in enumerate(chunks):
                embed.add_field(
                    name=f"Patrons {i*10+1}-{i*10+len(chunk)}" if len(chunks) > 1 else "Patrons",
                    value="\n".join(chunk),
                    inline=False
                )
            
            await ctx.send(embed=embed)
    
    async def refresh_access_token(self, guild) -> Union[bool, str]:
        """Refresh the Patreon access token"""
        settings = await self.config.guild(guild).api_settings()
        
        if not all([settings["client_id"], settings["client_secret"], settings["creator_refresh_token"]]):
            return "Missing required API credentials"
        
        data = {
            "grant_type": "refresh_token",
            "refresh_token": settings["creator_refresh_token"],
            "client_id": settings["client_id"],
            "client_secret": settings["client_secret"]
        }
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        try:
            async with self.session.post(
                "https://www.patreon.com/api/oauth2/token",
                data=data,
                headers=headers
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    return f"Failed to refresh token: HTTP {resp.status} - {error_text}"
                
                response_data = await resp.json()
                
                async with self.config.guild(guild).api_settings() as api_settings:
                    api_settings["creator_access_token"] = response_data["access_token"]
                    if "refresh_token" in response_data:
                        api_settings["creator_refresh_token"] = response_data["refresh_token"]
                
                return True
        except Exception as e:
            return f"Error refreshing token: {str(e)}"
    
    async def check_and_process_donations(self, guild) -> Union[Dict[str, int], str]:
        """
        Check for new Patreon donations and process them
        
        Returns dict with count of new and recurring donations processed, or error string
        """
        settings = await self.config.guild(guild).api_settings()
        
        if not all([settings["creator_access_token"], settings["campaign_id"]]):
            return "Missing required API credentials"
        
        # Update the last check time
        await self.config.guild(guild).last_check.set(datetime.utcnow().isoformat())
        
        try:
            # Get memberships (patrons) from Patreon API
            processed_map = await self.config.guild(guild).processed_donations()
            min_amount = await self.config.guild(guild).min_donation_amount()
            process_monthly = await self.config.guild(guild).process_monthly()
            
            # Get Patreon members with related pledge info from the API
            members = await self.get_campaign_members(guild)
            
            if isinstance(members, str):
                return members  # Error message
            
            # Get Discord-Patreon connections
            connections = await self.config.guild(guild).patreon_discord_connections()
            
            # Process donations
            new_count = 0
            recurring_count = 0
            
            for member in members:
                try:
                    # Extract member info
                    member_id = member.get("id")
                    attributes = member.get("attributes", {})
                    relationships = member.get("relationships", {})
                    
                    # Check if there's an amount to process
                    amount_cents = attributes.get("currently_entitled_amount_cents", 0)
                    if not amount_cents:
                        continue
                    
                    amount_dollars = amount_cents / 100
                    
                    # Skip if below minimum amount
                    if amount_dollars < min_amount:
                        continue
                    
                    # Get the last charge date
                    last_charge_date = attributes.get("last_charge_date")
                    
                    if not last_charge_date:
                        continue
                    
                    # Check if this is a new patron or a recurring payment
                    is_new_patron = member_id not in processed_map
                    
                    # For existing patrons, check if we have a new charge to process
                    if not is_new_patron:
                        last_processed_date = processed_map[member_id]
                        
                        # Skip if we've already processed this charge date
                        if last_processed_date == last_charge_date:
                            continue
                        
                        # Skip recurring donations if disabled
                        if not process_monthly:
                            continue
                    
                    # Get user relationship
                    user_relationship = relationships.get("user", {}).get("data", {})
                    user_id = user_relationship.get("id")
                    
                    if not user_id:
                        continue
                    
                    # Try to get Discord connection from social connections
                    user_data = None
                    for included in member.get("included", []):
                        if included.get("type") == "user" and included.get("id") == user_id:
                            user_data = included
                            break
                    
                    discord_id = None
                    patron_name = None
                    
                    if user_data:
                        # Get patron name
                        attributes = user_data.get("attributes", {})
                        patron_name = attributes.get("full_name", "Unknown Patron")
                        
                        # Check for Discord connection in social connections
                        social_connections = attributes.get("social_connections", {})
                        discord_connection = social_connections.get("discord")
                        
                        if discord_connection:
                            discord_id = discord_connection.get("user_id")
                    
                    # If no Discord ID from social connections, check our stored mappings
                    if not discord_id and user_id in connections:
                        discord_id = connections[user_id]
                    
                    # Skip if we don't have a Discord ID
                    if not discord_id:
                        continue
                    
                    # Determine donation type for message format
                    donation_type = "new" if is_new_patron else "monthly"
                    
                    # Send the award message
                    success = await self.send_award_message(
                        guild, 
                        amount_dollars, 
                        discord_id, 
                        patron_name,
                        donation_type
                    )
                    
                    if success:
                        # Add to processed map with last charge date
                        processed_map[member_id] = last_charge_date
                        
                        # Increment appropriate counter
                        if is_new_patron:
                            new_count += 1
                        else:
                            recurring_count += 1
                
                except Exception as e:
                    self.bot.logger.error(f"Error processing member {member.get('id')}: {e}", exc_info=True)
            
            # Save processed donations
            await self.config.guild(guild).processed_donations.set(processed_map)
            
            return {"new": new_count, "recurring": recurring_count}
            
        except Exception as e:
            return f"Error checking patrons: {str(e)}"
    
    async def get_campaign_members(self, guild) -> Union[List[Dict], str]:
        """Get members (patrons) from the Patreon API for a campaign"""
        settings = await self.config.guild(guild).api_settings()
        
        if not settings["creator_access_token"] or not settings["campaign_id"]:
            return "Missing required Patreon API credentials"
        
        headers = {
            "Authorization": f"Bearer {settings['creator_access_token']}",
            "Content-Type": "application/json"
        }
        
        # Build the URL with includes for all the data we need
        url = (
            f"https://www.patreon.com/api/oauth2/v2/campaigns/{settings['campaign_id']}/members"
            f"?include=user,currently_entitled_tiers"
            f"&fields%5Bmember%5D=currently_entitled_amount_cents,full_name,last_charge_date,patron_status"
            f"&fields%5Buser%5D=full_name,social_connections,email"
        )
        
        all_members = []
        
        try:
            while url:
                async with self.session.get(url, headers=headers) as resp:
                    if resp.status == 401:
                        # Token expired, try to refresh
                        refresh_result = await self.refresh_access_token(guild)
                        if isinstance(refresh_result, str):
                            return f"Failed to refresh token: {refresh_result}"
                        
                        # Update the token for the next request
                        settings = await self.config.guild(guild).api_settings()
                        headers["Authorization"] = f"Bearer {settings['creator_access_token']}"
                        continue
                    
                    if resp.status != 200:
                        error_text = await resp.text()
                        return f"Failed to get patrons: HTTP {resp.status} - {error_text}"
                    
                    data = await resp.json()
                    
                    # Add these members to our list
                    members = data.get("data", [])
                    for member in members:
                        member["included"] = data.get("included", [])
                    
                    all_members.extend(members)
                    
                    # Check for pagination
                    links = data.get("links", {})
                    url = links.get("next")
                    
                    # Avoid rate limits
                    await asyncio.sleep(1)
        
        except Exception as e:
            return f"Error fetching patrons: {str(e)}"
        
        return all_members
    
    async def send_award_message(self, guild, amount: float, discord_id: str, 
                                patron_name: str = None, donation_type: str = "new") -> bool:
        """Send the award message for a patron"""
        message_format = await self.config.guild(guild).message_format()
        
        try:
            # Get the hardcoded award channel
            channel = self.bot.get_channel(self.AWARD_CHANNEL_ID)
            if not channel:
                self.bot.logger.error(f"Award channel with ID {self.AWARD_CHANNEL_ID} not found in any guild")
                return False
            
            # Get the Discord user
            try:
                discord_user = await guild.fetch_member(int(discord_id))
            except (discord.NotFound, discord.HTTPException):
                # Try to get the user from the bot's cache
                discord_user = self.bot.get_user(int(discord_id))
                if not discord_user:
                    return False
            
            # Calculate award amount (3000 per 1 EUR/USD donated) with tier bonuses
            base_amount = amount * 3000
            
            # Apply bonus percentage based on donation tier
            if amount >= 40:
                # 20% bonus for 40+ EUR donations
                bonus_multiplier = 1.20
            elif amount >= 20:
                # 15% bonus for 20-39.99 EUR donations
                bonus_multiplier = 1.15
            elif amount >= 10:
                # 10% bonus for 10-19.99 EUR donations
                bonus_multiplier = 1.10
            elif amount >= 5:
                # 5% bonus for 5-9.99 EUR donations
                bonus_multiplier = 1.05
            else:
                # No bonus for donations under 5 EUR
                bonus_multiplier = 1.0
                
            # Apply bonus and convert to integer
            converted_amount = int(base_amount * bonus_multiplier)
            
            # Format the message
            message = message_format.format(
                amount=converted_amount,
                discord_user=discord_user.mention,
                patron_name=patron_name or "Unknown Patron",
                recurring=donation_type
            )
            
            # Send the message
            await channel.send(message)
            return True
            
        except Exception as e:
            self.bot.logger.error(f"Error sending award message: {e}", exc_info=True)
            return False 