"""
Currency generation and decay systems for Unicornia
"""

import random
import asyncio
import time
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
        
        # Check if password is required
        has_password = await self.config.generation_has_password()
        if has_password:
            password = self._generate_password()
            # Store the plant for pickup
            await self._create_plant(message.guild.id, message.channel.id, amount, password)
            
            # Send plant message
            embed = discord.Embed(
                title="<:slut:686148402941001730> Slut points Planted!",
                description=f"Someone planted {amount} Slut points! Use `[p]pick {password}` to claim it!",
                color=discord.Color.gold()
            )
            await message.channel.send(embed=embed)
        else:
            # Direct currency award
            await self.db.economy.add_currency(user_id, amount, "generation", "message", note="Random Slut points generation")
            
            currency_symbol = await self.config.currency_symbol()
            await message.channel.send(f"<:slut:686148402941001730> {message.author.mention} found {currency_symbol}{amount}!")
        
        # Update cooldown
        self.generation_cooldowns[user_id] = current_time
    
    def _generate_password(self) -> str:
        """Generate a random password for currency plants"""
        # Simple password generation - can be made more complex
        chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        return ''.join(random.choice(chars) for _ in range(6))
    
    async def _create_plant(self, guild_id: int, channel_id: int, amount: int, password: str):
        """Create a currency plant"""
        async with self.db._get_connection() as db:
            await self.db._setup_wal_mode(db)
            await db.execute("""
                INSERT INTO PlantedCurrency (GuildId, ChannelId, Amount, Password)
                VALUES (?, ?, ?, ?)
            """, (guild_id, channel_id, amount, password))
            await db.commit()
    
    async def pick_plant(self, user_id: int, guild_id: int, password: str) -> bool:
        """Pick up a currency plant"""
        async with self.db._get_connection() as db:
            await self.db._setup_wal_mode(db)
            # Find and remove the plant
            cursor = await db.execute("""
                SELECT Id, Amount FROM PlantedCurrency
                WHERE GuildId = ? AND Password = ?
                ORDER BY Id DESC LIMIT 1
            """, (guild_id, password))
            
            plant = await cursor.fetchone()
            if not plant:
                return False
            
            plant_id, amount = plant
            
            # Remove the plant
            await db.execute("DELETE FROM PlantedCurrency WHERE Id = ?", (plant_id,))
            
            # Give currency to user
            await self.db.economy.add_currency(user_id, amount, "plant_pick", password, note=f"Picked plant with password {password}")
            
            await db.commit()
            return True


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