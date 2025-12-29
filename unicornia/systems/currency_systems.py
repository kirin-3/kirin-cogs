"""
Currency generation and decay systems for Unicornia
"""

import random
import asyncio
import time
import os
import aiosqlite
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import discord
from redbot.core import commands
from ..database import DatabaseManager


class CurrencyGeneration:
    """Handles random currency generation in messages"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
        self.generation_cooldowns = {}  # {user_id: timestamp}
        self.active_plants = {}  # {guild_id: {channel_id: plant_data}}
    
    async def process_message(self, message: discord.Message):
        """Process a message for potential currency generation"""
        if message.author.bot or not message.guild:
            return
        
        if not await self.config.currency_generation_enabled():
            return
        
        # Check if channel is in the allowed list
        generation_channels = await self.config.generation_channels()
        if message.channel.id not in generation_channels:
            return

        # Check cooldown
        user_id = message.author.id
        current_time = time.time()
        
        if user_id in self.generation_cooldowns:
            if current_time - self.generation_cooldowns[user_id] < await self.config.generation_cooldown():
                return
        
        # Check generation chance
        chance = await self.config.generation_chance()
        if random.random() > chance:
            return
        
        # Generate currency
        min_amount = await self.config.generation_min_amount()
        max_amount = await self.config.generation_max_amount()
        amount = random.randint(min_amount, max_amount)
        
        # Store the plant for pickup (no password)
        await self._create_plant(message.guild.id, message.channel.id, amount)
        
        # Get random image
        cog_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        images_dir = os.path.join(cog_dir, "data", "currency_images")
        image_file = None
        
        if os.path.exists(images_dir):
            images = [f for f in os.listdir(images_dir) if f.lower().endswith('.png')]
            if images:
                image_file = random.choice(images)
                
        currency_symbol = await self.config.currency_symbol()
        
        msg_content = f"A wild {amount}{currency_symbol} has appeared! Pick them up by typing `&pick`"
        
        if image_file:
            image_path = os.path.join(images_dir, image_file)
            try:
                file = discord.File(image_path, filename="currency.png")
                await message.channel.send(content=msg_content, file=file)
            except Exception as e:
                print(f"Error sending currency generation image: {e}")
                await message.channel.send(content=msg_content)
        else:
            await message.channel.send(content=msg_content)

        # Update cooldown
        self.generation_cooldowns[user_id] = current_time
    
    async def _create_plant(self, guild_id: int, channel_id: int, amount: int):
        """Create a currency plant"""
        async with self.db._get_connection() as db:
            await self.db._setup_wal_mode(db)
            await db.execute("""
                INSERT INTO PlantedCurrency (GuildId, ChannelId, Amount, Password)
                VALUES (?, ?, ?, ?)
            """, (guild_id, channel_id, amount, "")) # Empty password
            await db.commit()
    
    async def pick_plant(self, user_id: int, channel_id: int) -> Optional[int]:
        """Pick up the last currency plant in the channel"""
        async with self.db._get_connection() as db:
            await self.db._setup_wal_mode(db)
            # Find the last plant in this channel
            cursor = await db.execute("""
                SELECT Id, Amount FROM PlantedCurrency
                WHERE ChannelId = ?
                ORDER BY Id DESC LIMIT 1
            """, (channel_id,))
            
            plant = await cursor.fetchone()
            if not plant:
                return None
            
            plant_id, amount = plant
            
            # Remove the plant
            await db.execute("DELETE FROM PlantedCurrency WHERE Id = ?", (plant_id,))
            
            # Give currency to user
            await self.db.economy.add_currency(user_id, amount, "plant_pick", str(plant_id), note=f"Picked plant {plant_id}")
            
            await db.commit()
            return amount


class CurrencyDecay:
    """Handles automatic currency decay over time"""
    
    def __init__(self, db: DatabaseManager, config, bot):
        self.db = db
        self.config = config
        self.bot = bot
        self._decay_task = None
    
    async def start_decay_loop(self):
        """Start the currency decay loop"""
        if self._decay_task:
            return
        
        self._decay_task = asyncio.create_task(self._decay_loop())
    
    async def stop_decay_loop(self):
        """Stop the currency decay loop"""
        if self._decay_task:
            self._decay_task.cancel()
            self._decay_task = None
    
    async def _decay_loop(self):
        """Main decay loop"""
        while True:
            try:
                await self._process_decay()
                
                # Wait for the next decay interval
                interval_hours = await self.config.decay_hour_interval()
                await asyncio.sleep(interval_hours * 3600)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in currency decay loop: {e}")
                await asyncio.sleep(3600)  # Wait 1 hour before retrying
    
    async def _process_decay(self):
        """Process currency decay for all users (Batch optimized)"""
        decay_percent = await self.config.decay_percent()
        max_decay = await self.config.decay_max_amount()
        min_threshold = await self.config.decay_min_threshold()
        
        if decay_percent <= 0:
            return
        
        async with self.db._get_connection() as db:
            await self.db._setup_wal_mode(db)
            # Get all users above threshold
            cursor = await db.execute("""
                SELECT UserId, CurrencyAmount FROM DiscordUser 
                WHERE CurrencyAmount > ? AND UserId != ?
            """, (min_threshold, self.bot.user.id))
            
            users = await cursor.fetchall()
            
            updates = []
            transactions = []
            timestamp = datetime.now().isoformat()
            
            for user_id, current_amount in users:
                # Calculate decay amount
                decay_amount = int(current_amount * decay_percent)
                
                if max_decay > 0:
                    decay_amount = min(decay_amount, max_decay)
                
                if decay_amount > 0:
                    # Add to batch
                    updates.append((decay_amount, user_id))
                    transactions.append((user_id, -decay_amount, 'decay', 'system', f"Slut points decay: {decay_percent:.1%}"))
            
            if updates:
                # Execute batch updates
                await db.executemany("""
                    UPDATE DiscordUser 
                    SET CurrencyAmount = CurrencyAmount - ? 
                    WHERE UserId = ?
                """, updates)
                
                await db.executemany("""
                    INSERT INTO currency_transactions (user_id, amount, type, extra, note)
                    VALUES (?, ?, ?, ?, ?)
                """, transactions)
                
                await db.commit()
                # print(f"Processed decay for {len(updates)} users")
    
    async def get_decay_stats(self) -> Dict[str, Any]:
        """Get decay statistics"""
        decay_percent = await self.config.decay_percent()
        max_decay = await self.config.decay_max_amount()
        min_threshold = await self.config.decay_min_threshold()
        interval_hours = await self.config.decay_hour_interval()
        
        return {
            "decay_percent": decay_percent,
            "max_decay": max_decay,
            "min_threshold": min_threshold,
            "interval_hours": interval_hours,
            "enabled": decay_percent > 0
        }