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
        
        # Config cache
        self.gen_enabled = False
        self.gen_channels = set()
        self.gen_cooldown = 10
        self.gen_chance = 0.005
        self.gen_min = 60
        self.gen_max = 140
        self.currency_symbol = ""
        
        # Initialize cache
        asyncio.create_task(self.refresh_config_cache())

    async def refresh_config_cache(self):
        """Refresh configuration cache"""
        self.gen_enabled = await self.config.currency_generation_enabled()
        self.gen_channels = set(await self.config.generation_channels())
        self.gen_cooldown = await self.config.generation_cooldown()
        self.gen_chance = await self.config.generation_chance()
        self.gen_min = await self.config.generation_min_amount()
        self.gen_max = await self.config.generation_max_amount()
        self.currency_symbol = await self.config.currency_symbol()

    async def process_message(self, message: discord.Message):
        """Process a message for potential currency generation"""
        if message.author.bot or not message.guild:
            return
        
        # Fast checks using cache
        if not self.gen_enabled:
            return
        
        if message.channel.id not in self.gen_channels:
            return

        # Check cooldown
        user_id = message.author.id
        current_time = time.time()
        
        if user_id in self.generation_cooldowns:
            if current_time - self.generation_cooldowns[user_id] < self.gen_cooldown:
                return
        
        # Check generation chance
        if random.random() > self.gen_chance:
            return
        
        # Generate currency
        amount = random.randint(self.gen_min, self.gen_max)
        
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
        
        msg_content = f"A wild {amount}{self.currency_symbol} has appeared! Pick them up by typing `&pick`"
        
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
            
            # Remove the plant (Atomic check using rowcount)
            cursor = await db.execute("DELETE FROM PlantedCurrency WHERE Id = ?", (plant_id,))
            
            if cursor.rowcount == 0:
                # Already picked by someone else in the split second between SELECT and DELETE
                await db.commit()
                return None
            
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
        await self.bot.wait_until_ready()
        
        while True:
            try:
                interval_hours = await self.config.decay_hour_interval()
                last_run = await self.config.decay_last_run()
                current_time = time.time()
                
                # Check if enough time has passed since last run
                if current_time - last_run >= interval_hours * 3600:
                    await self._process_decay()
                    await self.config.decay_last_run.set(int(time.time()))
                    
                    # Wait full interval before next check
                    await asyncio.sleep(interval_hours * 3600)
                else:
                    # Wait remaining time
                    remaining = (interval_hours * 3600) - (current_time - last_run)
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                    else:
                        await asyncio.sleep(60) # Fallback safety
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in currency decay loop: {e}")
                await asyncio.sleep(3600)  # Wait 1 hour before retrying
    
    async def _process_decay(self):
        """Process currency decay for all users (Batch optimized) including bank"""
        decay_percent = await self.config.decay_percent()
        max_decay = await self.config.decay_max_amount()
        min_threshold = await self.config.decay_min_threshold()
        
        if decay_percent <= 0:
            return
        
        async with self.db._get_connection() as db:
            await self.db._setup_wal_mode(db)
            
            # Get wallet balances
            cursor = await db.execute("""
                SELECT UserId, CurrencyAmount FROM DiscordUser
                WHERE CurrencyAmount > 0 AND UserId != ?
            """, (self.bot.user.id,))
            wallet_users = await cursor.fetchall()
            
            # Get bank balances
            cursor = await db.execute("""
                SELECT UserId, Balance FROM BankUsers
                WHERE Balance > 0
            """)
            bank_users = await cursor.fetchall()
            
            # Combine into a map {user_id: {'wallet': 0, 'bank': 0}}
            user_balances = {}
            for uid, amt in wallet_users:
                if uid not in user_balances: user_balances[uid] = {'wallet': 0, 'bank': 0}
                user_balances[uid]['wallet'] = amt
                
            for uid, amt in bank_users:
                if uid not in user_balances: user_balances[uid] = {'wallet': 0, 'bank': 0}
                user_balances[uid]['bank'] = amt
            
            wallet_updates = []
            bank_updates = []
            transactions = []
            
            for user_id, balances in user_balances.items():
                total_wealth = balances['wallet'] + balances['bank']
                
                # Check minimum threshold
                if total_wealth < min_threshold:
                    continue
                    
                # Calculate decay based on total wealth
                total_decay = int(total_wealth * decay_percent)
                
                # Cap max decay
                if max_decay > 0:
                    total_decay = min(total_decay, max_decay)
                
                if total_decay <= 0:
                    continue
                
                # Decay from wallet first, then bank
                wallet_decay = min(balances['wallet'], total_decay)
                bank_decay = total_decay - wallet_decay
                
                if wallet_decay > 0:
                    wallet_updates.append((wallet_decay, user_id))
                    transactions.append((user_id, -wallet_decay, 'decay', 'system', f"Wallet decay: {decay_percent:.1%}"))
                    
                if bank_decay > 0:
                    bank_updates.append((bank_decay, user_id))
                    transactions.append((user_id, -bank_decay, 'decay', 'system', f"Bank decay: {decay_percent:.1%}"))
            
            if wallet_updates:
                await db.executemany("""
                    UPDATE DiscordUser
                    SET CurrencyAmount = MAX(0, CurrencyAmount - ?)
                    WHERE UserId = ?
                """, wallet_updates)
                
            if bank_updates:
                await db.executemany("""
                    UPDATE BankUsers
                    SET Balance = MAX(0, Balance - ?)
                    WHERE UserId = ?
                """, bank_updates)
                
            if transactions:
                # Need to map transaction columns correctly to schema
                # Schema: UserId, Amount, Type, Extra, OtherId, Reason, DateAdded
                # Our list has: (user_id, amount, type, extra, note)
                # Adjust to: (user_id, amount, type, extra, None, note)
                formatted_transactions = [(uid, amt, typ, ext, None, note) for uid, amt, typ, ext, note in transactions]
                
                await db.executemany("""
                    INSERT INTO CurrencyTransactions (UserId, Amount, Type, Extra, OtherId, Reason, DateAdded)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """, formatted_transactions)
                
            if wallet_updates or bank_updates:
                await db.commit()
                # print(f"Processed decay for {len(wallet_updates) + len(bank_updates)} balances")
    
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