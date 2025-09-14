"""
XP and Leveling system for Unicornia
"""

import time
import discord
from typing import Optional, Dict, Any
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_number
from .database import DatabaseManager, LevelStats
from .xp_card_generator import XPCardGenerator
import os


class XPSystem:
    """Handles XP gain, leveling, and rewards"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
        self.xp_cooldowns = {}  # {user_id: timestamp}
        
        # Initialize XP card generator
        cog_dir = os.path.dirname(os.path.abspath(__file__))
        self.card_generator = XPCardGenerator(cog_dir)
    
    async def process_message(self, message: discord.Message):
        """Process a message for XP gain"""
        if message.author.bot or not message.guild:
            return
        
        if not await self.config.xp_enabled():
            return
        
        if not await self.config.guild(message.guild).xp_enabled():
            return
        
        # Check cooldown
        user_id = message.author.id
        current_time = time.time()
        
        if user_id in self.xp_cooldowns:
            if current_time - self.xp_cooldowns[user_id] < await self.config.xp_cooldown():
                return
        
        # Check exclusions (both config and database)
        excluded_channels = await self.config.guild(message.guild).excluded_channels()
        excluded_roles = await self.config.guild(message.guild).excluded_roles()
        
        if message.channel.id in excluded_channels:
            return
        
        if any(role.id in excluded_roles for role in message.author.roles):
            return
            
        # Also check database exclusions
        if await self.db.is_xp_excluded(message.guild.id, message.channel.id, 0):  # 0 = Channel
            return
            
        for role in message.author.roles:
            if await self.db.is_xp_excluded(message.guild.id, role.id, 1):  # 1 = Role
                return
        
        # Add XP
        xp_amount = await self.config.xp_per_message()
        old_xp = await self.db.get_user_xp(user_id, message.guild.id)
        old_level = self.db.calculate_level_stats(old_xp).level
        
        await self.db.add_xp(user_id, message.guild.id, xp_amount)
        
        # Check for level up
        new_xp = await self.db.get_user_xp(user_id, message.guild.id)
        new_level = self.db.calculate_level_stats(new_xp).level
        
        if new_level > old_level:
            await self._handle_level_up(message, old_level, new_level)
            await self._handle_role_rewards(message, new_level)
        
        # Update cooldown
        self.xp_cooldowns[user_id] = current_time
    
    async def _handle_role_rewards(self, message, level: int):
        """Handle role rewards for reaching a level"""
        try:
            # Get role rewards for this level
            role_rewards = await self.db.get_xp_role_rewards(message.guild.id, level)
            
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
            log = logging.getLogger("red.unicornia.xp")
            log.error(f"Error handling role rewards for level {level}: {e}")
    
    async def _handle_level_up(self, message, old_level: int, new_level: int):
        """Handle level up rewards and notifications"""
        user = message.author
        guild = message.guild
        
        # Check if level up messages are enabled
        if not await self.config.guild(guild).level_up_messages():
            return
        
        # Get level up channel
        level_up_channel_id = await self.config.guild(guild).level_up_channel()
        if level_up_channel_id:
            channel = guild.get_channel(level_up_channel_id)
        else:
            channel = message.channel
        
        if not channel:
            return
        
        # Send level up message
        embed = discord.Embed(
            title="🎉 Level Up!",
            description=f"{user.mention} has reached level **{new_level}**!",
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
        
        # Check for role rewards
        role_rewards = await self.config.guild(guild).role_rewards()
        for level, role_id in role_rewards.items():
            if new_level >= int(level):
                role = guild.get_role(role_id)
                if role and role not in user.roles:
                    try:
                        await user.add_roles(role, reason=f"Level {new_level} reward")
                        embed.add_field(name="🎁 Role Reward", value=f"You received the {role.mention} role!", inline=False)
                    except discord.Forbidden:
                        embed.add_field(name="⚠️ Role Reward", value=f"You earned the {role.name} role, but I couldn't assign it.", inline=False)
        
        # Check for currency rewards
        currency_rewards = await self.config.guild(guild).currency_rewards()
        for level, amount in currency_rewards.items():
            if new_level >= int(level):
                await self.db.add_currency(user.id, amount, "level_reward", f"level_{level}", note=f"Level {level} reward")
                currency_symbol = await self.config.currency_symbol()
                embed.add_field(name="💰 Currency Reward", value=f"You received {currency_symbol}{amount:,}!", inline=False)
        
        await channel.send(embed=embed)
    
    async def get_user_level_stats(self, user_id: int, guild_id: int) -> LevelStats:
        """Get user's level statistics"""
        xp = await self.db.get_user_xp(user_id, guild_id)
        return self.db.calculate_level_stats(xp)
    
    async def get_leaderboard(self, guild_id: int, limit: int = 10, offset: int = 0):
        """Get XP leaderboard for a guild"""
        return await self.db.get_top_xp_users(guild_id, limit, offset)
    
    def get_progress_bar(self, current_xp: int, required_xp: int, length: int = 10) -> str:
        """Generate a progress bar for XP"""
        if required_xp == 0:
            return "█" * length
        
        filled_length = int(length * current_xp / required_xp)
        bar = "█" * filled_length + "░" * (length - filled_length)
        return bar
