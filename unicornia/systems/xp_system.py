"""
XP and Leveling system for Unicornia
"""

import time
import discord
from typing import Optional, List, Tuple
from collections import OrderedDict
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_number
from ..database import DatabaseManager
from ..types import LevelStats
from .card_generator import XPCardGenerator
import os
import asyncio


class XPSystem:
    """Handles XP gain, leveling, and rewards"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
        self.xp_cooldowns = {}  # {user_id: timestamp}
        self.xp_buffer = {} # {(user_id, guild_id): amount}
        # Config Cache
        self._config_cache = {
            "xp_enabled": True,
            "xp_cooldown": 60,
            "xp_per_message": 1
        }
        self._guild_config_cache = {} # {guild_id: {'xp_included_channels': set(), 'excluded_roles': set()}}
        
        # User XP Cache (LRU) - Stores { (user_id, guild_id): {'xp': int, 'level': int, 'req_xp': int} }
        self.user_xp_cache = OrderedDict()
        self.user_xp_cache_size = 5000
        
        self._voice_xp_task = None
        self._message_xp_task = None
        
        # Initialize XP card generator
        # Pass the cog root directory (parent of 'systems')
        cog_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.card_generator = XPCardGenerator(cog_dir)
        
        # Start loops
        self.start_loops()
        
        # Initialize Config Cache
        asyncio.create_task(self._init_config_cache())

    async def _init_config_cache(self):
        """Initialize configuration cache"""
        self._config_cache["xp_enabled"] = await self.config.xp_enabled()
        self._config_cache["xp_cooldown"] = await self.config.xp_cooldown()
        self._config_cache["xp_per_message"] = await self.config.xp_per_message()

    def start_loops(self):
        """Start XP loops"""
        if not self._voice_xp_task:
            self._voice_xp_task = asyncio.create_task(self._voice_xp_loop())
        if not self._message_xp_task:
            self._message_xp_task = asyncio.create_task(self._message_xp_loop())

    def stop_loops(self):
        """Stop XP loops"""
        if self._voice_xp_task:
            self._voice_xp_task.cancel()
            self._voice_xp_task = None
        if self._message_xp_task:
            self._message_xp_task.cancel()
            self._message_xp_task = None
            
        # Flush remaining buffer
        if self.xp_buffer:
            asyncio.create_task(self._flush_buffer())

    async def _voice_xp_loop(self):
        """Background task to award XP to users in voice channels"""
        await self.bot.wait_until_ready()
        
        while True:
            try:
                # Wait for 1 minute
                await asyncio.sleep(60)
                
                # Check global enable (Cached)
                if not self._config_cache.get("xp_enabled", True):
                    continue
                
                xp_amount = 1 # Trickle amount per minute
                pending_updates = []
                
                for guild in self.bot.guilds:
                    # Get whitelist and exclusions (Config)
                    included_channels = set(await self.config.guild(guild).xp_included_channels())
                    double_xp_channels = set(await self.config.guild(guild).xp_double_channels())
                    excluded_roles = set(await self.config.guild(guild).excluded_roles())
                    
                    for channel in guild.voice_channels:
                        # Skip if channel is not in whitelist
                        if channel.id not in included_channels:
                            continue
                        
                        # Calculate XP amount for this channel
                        current_xp_amount = xp_amount
                        if channel.id in double_xp_channels:
                            current_xp_amount *= 2

                        # Process members
                        for member in channel.members:
                            if member.bot:
                                continue
                                
                            # Skip self-deafened or afk (optional, but good for anti-abuse)
                            if member.voice.self_deaf or member.voice.deaf:
                                continue
                                
                            # Skip excluded roles
                            if any(role.id in excluded_roles for role in member.roles):
                                continue
                            
                            # Add to batch
                            pending_updates.append((member.id, guild.id, current_xp_amount))
                
                # Process bulk update
                if pending_updates:
                    await self.db.xp.add_xp_bulk(pending_updates)
                            
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in voice XP loop: {e}")
                await asyncio.sleep(60) # Wait before retry

    async def _message_xp_loop(self):
        """Background task to flush message XP buffer and clean memory"""
        counter = 0
        while True:
            try:
                await asyncio.sleep(30) # Flush every 30 seconds
                await self._flush_buffer()
                
                # Cleanup cooldowns every 10 minutes (20 iterations)
                counter += 1
                if counter >= 20:
                    self._cleanup_cooldowns()
                    counter = 0
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in message XP loop: {e}")
                await asyncio.sleep(30)

    def _cleanup_cooldowns(self):
        """Remove stale cooldown entries to prevent memory leaks"""
        current_time = time.time()
        # Default cooldown 60s, checking 120s ensures we don't delete active cooldowns
        # Using 3600 (1 hour) as a safe stale threshold
        stale_threshold = 3600 
        
        to_remove = [
            user_id for user_id, timestamp in self.xp_cooldowns.items()
            if current_time - timestamp > stale_threshold
        ]
        
        for user_id in to_remove:
            del self.xp_cooldowns[user_id]

    async def _flush_buffer(self):
        """Flush the XP buffer to the database"""
        if not self.xp_buffer:
            return
            
        # Copy and clear buffer
        current_buffer = self.xp_buffer.copy()
        self.xp_buffer.clear()
        
        # Convert to list for bulk update: (user_id, guild_id, amount)
        updates = [(uid, gid, amount) for (uid, gid), amount in current_buffer.items()]
        
        # We assume cache is already updated during process_message
        try:
            await self.db.xp.add_xp_bulk(updates)
        except Exception as e:
            # If DB write fails, restore buffer to prevent data loss
            import logging
            log = logging.getLogger("red.kirin_cogs.unicornia.xp")
            log.error(f"Failed to flush XP buffer: {e}. Restoring {len(updates)} entries.")
            
            # Merge back into current buffer (which might have new entries)
            for key, amount in current_buffer.items():
                if key in self.xp_buffer:
                    self.xp_buffer[key] += amount
                else:
                    self.xp_buffer[key] = amount

    def _get_user_cache_data(self, user_id: int, guild_id: int):
        """Get user data from cache, handling LRU"""
        key = (user_id, guild_id)
        if key in self.user_xp_cache:
            self.user_xp_cache.move_to_end(key)
            return self.user_xp_cache[key]
        return None

    def _set_user_cache_data(self, user_id: int, guild_id: int, data: dict):
        """Set user data in cache, handling LRU eviction"""
        key = (user_id, guild_id)
        self.user_xp_cache[key] = data
        self.user_xp_cache.move_to_end(key)
        
        if len(self.user_xp_cache) > self.user_xp_cache_size:
            self.user_xp_cache.popitem(last=False)

    async def process_message(self, message: discord.Message):
        """Process a message for XP gain (Optimized)"""
        if message.author.bot or not message.guild:
            return

        # Check if message is a command
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return
        
        # Check cached config
        if not self._config_cache.get("xp_enabled", True):
            return
        
        # Check cooldown
        user_id = message.author.id
        current_time = time.time()
        cooldown = self._config_cache.get("xp_cooldown", 60)
        
        if user_id in self.xp_cooldowns:
            if current_time - self.xp_cooldowns[user_id] < cooldown:
                return
        
        guild_id = message.guild.id
        
        # --- EXCLUSION CHECKS ---
        
        # 1. Channel Whitelist Check
        included_channels = await self.config.guild(message.guild).xp_included_channels()
        
        # Check channel ID directly
        channel_id = message.channel.id
        is_included = channel_id in included_channels
        
        # If not included, check if it's a thread and if parent is included
        if not is_included and isinstance(message.channel, discord.Thread):
            if message.channel.parent_id in included_channels:
                is_included = True
                
        if not is_included:
            return

        # 2. Role Exclusion Check
        excluded_roles = await self.config.guild(message.guild).excluded_roles()
        if any(role.id in excluded_roles for role in message.author.roles):
            return
            
        # --- XP CALCULATION (LRU Cache) ---
        
        xp_amount = self._config_cache.get("xp_per_message", 1)

        # Check for Double XP Channel
        double_xp_channels = await self.config.guild(message.guild).xp_double_channels()
        
        # Check channel ID directly
        is_double = channel_id in double_xp_channels
        
        # If not included, check if it's a thread and if parent is included
        if not is_double and isinstance(message.channel, discord.Thread):
            if message.channel.parent_id in double_xp_channels:
                is_double = True
        
        if is_double:
            xp_amount *= 2
        
        # Check cache
        cache_data = self._get_user_cache_data(user_id, guild_id)
        
        if cache_data:
            # Hit! Use cached data
            current_xp = cache_data['xp']
            # Add buffered XP not yet in DB/Cache base?
            # Actually, let's keep cache as "Total XP including buffer"
            
            new_total_xp = current_xp + xp_amount
            
            # Check level up using cached threshold
            if new_total_xp >= cache_data['req_xp']:
                # Potential level up - Recalculate everything to be sure
                new_stats = self.db.calculate_level_stats(new_total_xp)
                if new_stats.level > cache_data['level']:
                    await self._handle_level_up(message, cache_data['level'], new_stats.level)
                    
                # Update cache
                self._set_user_cache_data(user_id, guild_id, {
                    'xp': new_total_xp,
                    'level': new_stats.level,
                    'req_xp': new_stats.required_xp
                })
            else:
                # No level up, just update XP in cache
                cache_data['xp'] = new_total_xp
                # No need to move_to_end again, getter did it
        
        else:
            # Miss! Fetch from DB
            old_xp = await self.db.xp.get_user_xp(user_id, guild_id)
            
            # Check buffer (in case we have pending writes)
            key = (user_id, guild_id)
            buffered_xp = self.xp_buffer.get(key, 0)
            
            current_total_xp = old_xp + buffered_xp
            
            # Calculate stats
            stats = self.db.calculate_level_stats(current_total_xp)
            
            new_total_xp = current_total_xp + xp_amount
            new_stats = self.db.calculate_level_stats(new_total_xp)
            
            if new_stats.level > stats.level:
                await self._handle_level_up(message, stats.level, new_stats.level)
            
            # Populate cache
            self._set_user_cache_data(user_id, guild_id, {
                'xp': new_total_xp,
                'level': new_stats.level,
                'req_xp': new_stats.required_xp
            })

        # Add to write buffer
        key = (user_id, guild_id)
        if key in self.xp_buffer:
            self.xp_buffer[key] += xp_amount
        else:
            self.xp_buffer[key] = xp_amount
        
        # Update cooldown
        self.xp_cooldowns[user_id] = current_time
    
    async def _handle_role_rewards(self, message, level: int):
        """Handle role rewards for reaching a level"""
        try:
            # Get role rewards for this level
            role_rewards = await self.db.xp.get_xp_role_rewards(message.guild.id, level)
            
            for role_id, remove in role_rewards:
                role = message.guild.get_role(role_id)
                if not role:
                    continue
                    
                try:
                    if remove and role in message.author.roles:
                        await message.author.remove_roles(role, reason=f"XP level {level} role removal")
                    elif not remove and role not in message.author.roles:
                        await message.author.add_roles(role, reason=f"XP level {level} role reward")
                except discord.Forbidden:
                    pass  # Bot lacks permissions
                except discord.HTTPException:
                    pass  # Other Discord API error
                    
        except Exception as e:
            import logging
            log = logging.getLogger("red.kirin_cogs.unicornia.xp")
            log.error(f"Error handling role rewards for level {level}: {e}")
    
    async def _handle_level_up(self, message, old_level: int, new_level: int):
        """Handle level up rewards and notifications"""
        user = message.author
        guild = message.guild
        
        channel = message.channel
        
        # Random Color for Embed
        import random
        embed_color = discord.Color(random.randint(0, 0xFFFFFF))

        # Send level up message
        embed = discord.Embed(
            description=f"Congratulations {user.mention}, you have reached level **{new_level}**!",
            color=embed_color
        )
        
        # Footer text building
        footer_texts = []

        # Check for role rewards (from DB)
        
        role_rewards = await self.db.xp.get_xp_role_rewards(guild.id, new_level)
        for role_id, remove in role_rewards:
            role = guild.get_role(role_id)
            if not role:
                continue
            
            try:
                if remove and role in user.roles:
                    await user.remove_roles(role, reason=f"XP level {new_level} role removal")
                    footer_texts.append(f"Removed role: {role.name}")
                elif not remove and role not in user.roles:
                    await user.add_roles(role, reason=f"XP level {new_level} role reward")
                    footer_texts.append(f"Gained role: {role.name}")
            except discord.Forbidden:
                pass
        
        # Check for currency rewards (from DB)
        currency_rewards = await self.db.xp.get_xp_currency_rewards(guild.id)
        currency_gained = 0
        for level, amount in currency_rewards:
            if level == new_level and amount > 0:
                await self.db.economy.add_currency(user.id, amount, "level_reward", f"level_{new_level}", note=f"Level {new_level} reward")
                currency_gained += amount
        
        if currency_gained > 0:
            currency_name = await self.config.currency_name()
            footer_texts.append(f"Gained {currency_gained} {currency_name}")

        if footer_texts:
            embed.set_footer(text=" • ".join(footer_texts))
        
        await channel.send(embed=embed)
    
    async def get_user_level_stats(self, user_id: int, guild_id: int) -> LevelStats:
        """Get user's level statistics.
        
        Args:
            user_id: User ID.
            guild_id: Guild ID.
            
        Returns:
            LevelStats object.
        """
        xp = await self.db.xp.get_user_xp(user_id, guild_id)
        return self.db.calculate_level_stats(xp)
    
    async def get_leaderboard(self, guild_id: int, limit: int = 10, offset: int = 0) -> List[Tuple]:
        """Get XP leaderboard for a guild.
        
        Args:
            guild_id: Guild ID.
            limit: Limit results.
            offset: Offset results.
            
        Returns:
            List of (UserId, Xp) tuples.
        """
        return await self.db.xp.get_top_xp_users(guild_id, limit, offset)

    async def get_filtered_leaderboard(self, guild: discord.Guild) -> List[Tuple]:
        """Get filtered XP leaderboard for a guild (only current members).
        
        Args:
            guild: Discord guild.
            
        Returns:
            List of (UserId, Xp) tuples.
        """
        all_users = await self.db.xp.get_all_guild_xp(guild.id)
        
        filtered_users = []
        for user_id, xp in all_users:
            member = guild.get_member(user_id)
            if member and not member.bot:
                filtered_users.append((user_id, xp))
        
        # Limit to 30 pages (300 users)
        return filtered_users[:300]
    
    def get_progress_bar(self, current_xp: int, required_xp: int, length: int = 10) -> str:
        """Generate a progress bar for XP.
        
        Args:
            current_xp: Current XP amount.
            required_xp: Required XP for next level.
            length: Length of the bar in characters.
            
        Returns:
            Progress bar string.
        """
        if required_xp == 0:
            return "█" * length
        
        filled_length = int(length * current_xp / required_xp)
        bar = "█" * filled_length + "░" * (length - filled_length)
        return bar
    
    async def award_xp(self, user_id: int, guild_id: int, amount: int, note: str = "") -> bool:
        """Award XP to a user (admin only).
        
        Args:
            user_id: User ID.
            guild_id: Guild ID.
            amount: Amount of XP to award.
            note: Optional note for the award.
            
        Returns:
            Success boolean.
        """
        if amount <= 0:
            return False
        
        try:
            await self.db.xp.add_xp(user_id, guild_id, amount)
            return True
        except Exception:
            return False