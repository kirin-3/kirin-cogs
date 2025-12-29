import discord
from redbot.core import commands, checks
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from typing import Optional
from ..utils import systems_ready

class AdminCommands:
    # Configuration commands
    @commands.group(name="unicornia", aliases=["uni"])
    async def unicornia_group(self, ctx):
        """Unicornia - Full-featured leveling and economy system"""
        pass

    @unicornia_group.group(name="gen")
    @checks.is_owner()
    async def gen_group(self, ctx):
        """Currency generation configuration"""
        pass

    @gen_group.command(name="channel")
    async def gen_channel(self, ctx, operation: str, channel: discord.TextChannel):
        """Add or remove a channel for currency generation (add/remove)"""
        if operation.lower() not in ["add", "remove"]:
            await ctx.send("❌ Operation must be 'add' or 'remove'.")
            return
            
        channels = await self.config.generation_channels()
        
        if operation.lower() == "add":
            if channel.id not in channels:
                channels.append(channel.id)
                await self.config.generation_channels.set(channels)
                await ctx.send(f"✅ Added {channel.mention} to currency generation channels.")
            else:
                await ctx.send(f"❌ {channel.mention} is already in the list.")
        else:
            if channel.id in channels:
                channels.remove(channel.id)
                await self.config.generation_channels.set(channels)
                await ctx.send(f"✅ Removed {channel.mention} from currency generation channels.")
            else:
                await ctx.send(f"❌ {channel.mention} is not in the list.")

    @gen_group.command(name="list")
    async def gen_list(self, ctx):
        """List currency generation channels"""
        channels = await self.config.generation_channels()
        if not channels:
            await ctx.send("No channels configured for currency generation.")
            return
            
        channel_mentions = [f"<#{cid}>" for cid in channels]
        await ctx.send(f"**Generation Channels:**\n{', '.join(channel_mentions)}")

    @unicornia_group.command(name="config")
    @checks.is_owner()
    @systems_ready
    async def config_cmd(self, ctx, setting: str, *, value: str):
        """Configure Unicornia settings"""
        valid_settings = [
            "currency_name", "currency_symbol", "xp_enabled", "economy_enabled",
            "gambling_enabled", "shop_enabled", "timely_amount", "timely_cooldown",
            "xp_per_message", "xp_cooldown", "currency_generation_enabled",
            "generation_chance", "generation_cooldown", "generation_min_amount",
            "generation_max_amount", "generation_has_password", "decay_percent",
            "decay_max_amount", "decay_min_threshold", "decay_hour_interval",
            "gambling_min_bet", "gambling_max_bet"
        ]
        
        if setting not in valid_settings:
            await ctx.send(f"Invalid setting. Valid options: {', '.join(valid_settings)}")
            return
        
        try:
            if setting in ["xp_enabled", "economy_enabled", "gambling_enabled", "shop_enabled", "currency_generation_enabled", "generation_has_password"]:
                enabled = value.lower() in ["true", "yes", "1", "on"]
                await getattr(self.config, setting).set(enabled)
                await ctx.send(f"✅ {setting} {'enabled' if enabled else 'disabled'}")
            elif setting in ["timely_amount", "timely_cooldown", "xp_per_message", "xp_cooldown", "generation_cooldown", "generation_min_amount", "generation_max_amount", "decay_max_amount", "decay_min_threshold", "decay_hour_interval", "gambling_min_bet", "gambling_max_bet"]:
                amount = int(value)
                if amount < 0:
                    await ctx.send("❌ Amount must be positive.")
                    return
                await getattr(self.config, setting).set(amount)
                await ctx.send(f"✅ {setting} updated to {amount}")
            elif setting == "generation_chance":
                chance = float(value)
                if not 0 <= chance <= 1:
                    await ctx.send("❌ Chance must be between 0 and 1.")
                    return
                await getattr(self.config, setting).set(chance)
                await ctx.send(f"✅ {setting} updated to {chance}")
            elif setting == "decay_percent":
                percent = float(value)
                if not 0 <= percent <= 1:
                    await ctx.send("❌ Decay percent must be between 0 and 1.")
                    return
                await getattr(self.config, setting).set(percent)
                await ctx.send(f"✅ {setting} updated to {percent}")
            else:
                await getattr(self.config, setting).set(value)
                await ctx.send(f"✅ {setting} updated to {value}")
                
        except ValueError:
            await ctx.send("❌ Invalid value type for this setting.")
        except Exception as e:
            await ctx.send(f"❌ Error updating setting: {e}")
    
    @unicornia_group.command(name="status")
    @systems_ready
    async def status(self, ctx):
        """Check Unicornia status and configuration"""
        embed = discord.Embed(
            title="🦄 Unicornia Status",
            color=discord.Color.green(),
            description="Full-featured leveling and economy system"
        )
        
        xp_enabled = await self.config.xp_enabled()
        economy_enabled = await self.config.economy_enabled()
        gambling_enabled = await self.config.gambling_enabled()
        shop_enabled = await self.config.shop_enabled()
        
        embed.add_field(name="XP System", value="✅ Enabled" if xp_enabled else "❌ Disabled", inline=True)
        embed.add_field(name="Economy System", value="✅ Enabled" if economy_enabled else "❌ Disabled", inline=True)
        embed.add_field(name="Gambling", value="✅ Enabled" if gambling_enabled else "❌ Disabled", inline=True)
        embed.add_field(name="Shop", value="✅ Enabled" if shop_enabled else "❌ Disabled", inline=True)
        
        currency_name = await self.config.currency_name()
        currency_symbol = await self.config.currency_symbol()
        embed.add_field(name="<:slut:686148402941001730> Slut points", value=f"{currency_symbol} {currency_name}", inline=True)
        
        timely_amount = await self.config.timely_amount()
        timely_cooldown = await self.config.timely_cooldown()
        embed.add_field(name="Daily Reward", value=f"{currency_symbol}{timely_amount} every {timely_cooldown}h", inline=True)
        
        await ctx.send(embed=embed)

    @unicornia_group.group(name="guild")
    @checks.admin()
    async def guild_config(self, ctx):
        """Guild-specific configuration"""
        pass
    
    @guild_config.command(name="excludechannel")
    @systems_ready
    async def guild_exclude_channel(self, ctx, channel: discord.TextChannel):
        """Exclude a channel from XP gain"""
        excluded = await self.config.guild(ctx.guild).excluded_channels()
        if channel.id not in excluded:
            excluded.append(channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(excluded)
            await ctx.send(f"✅ {channel.mention} excluded from XP gain.")
        else:
            await ctx.send(f"❌ {channel.mention} is already excluded from XP gain.")
    
    @guild_config.command(name="includechannel")
    @systems_ready
    async def guild_include_channel(self, ctx, channel: discord.TextChannel):
        """Include a channel in XP gain"""
        excluded = await self.config.guild(ctx.guild).excluded_channels()
        if channel.id in excluded:
            excluded.remove(channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(excluded)
            await ctx.send(f"✅ {channel.mention} included in XP gain.")
        else:
            await ctx.send(f"❌ {channel.mention} is not excluded from XP gain.")
    
    @guild_config.command(name="rolereward")
    @systems_ready
    async def guild_role_reward(self, ctx, level: int, role: discord.Role, remove: bool = False):
        """Set a role reward for reaching a level (remove=True to remove role from user)"""
        if level < 1:
            await ctx.send("❌ Level must be at least 1.")
            return
        
        await self.db.xp.add_xp_role_reward(ctx.guild.id, level, role.id, remove)
        action = "removed from" if remove else "given to"
        await ctx.send(f"✅ Users reaching level {level} will have {role.mention} {action} them.")

    @guild_config.command(name="removerolereward")
    @systems_ready
    async def guild_remove_role_reward(self, ctx, level: int, role: discord.Role):
        """Remove a configured role reward"""
        await self.db.xp.remove_xp_role_reward(ctx.guild.id, level, role.id)
        await ctx.send(f"✅ Removed role reward {role.mention} at level {level}.")
    
    @guild_config.command(name="currencyreward")
    @systems_ready
    async def guild_currency_reward(self, ctx, level: int, amount: int):
        """Set a currency reward for reaching a level (0 to remove)"""
        if level < 1:
            await ctx.send("❌ Level must be at least 1.")
            return
        
        if amount < 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        await self.db.xp.add_xp_currency_reward(ctx.guild.id, level, amount)
        currency_symbol = await self.config.currency_symbol()
        
        if amount == 0:
             await ctx.send(f"✅ Removed currency reward for level {level}.")
        else:
            await ctx.send(f"✅ Users reaching level {level} will receive {currency_symbol}{amount:,}.")

    @guild_config.command(name="listcurrencyrewards")
    @systems_ready
    async def guild_list_currency_rewards(self, ctx):
        """List currency rewards (paginated)"""
        currency_rewards = await self.db.xp.get_xp_currency_rewards(ctx.guild.id)
        
        if not currency_rewards:
            await ctx.send("No currency rewards configured.")
            return

        currency_symbol = await self.config.currency_symbol()
        
        # Sort by level just in case
        currency_rewards.sort(key=lambda x: x[0])
        
        chunks = [currency_rewards[i:i + 30] for i in range(0, len(currency_rewards), 30)]
        pages = []
        
        for i, chunk in enumerate(chunks, 1):
            embed = discord.Embed(
                title=f"Currency Rewards for {ctx.guild.name}",
                color=discord.Color.gold()
            )
            
            curr_text = ""
            for level, amount in chunk:
                curr_text += f"**Level {level}:** {currency_symbol}{amount:,}\n"
                
            embed.description = curr_text
            embed.set_footer(text=f"Page {i}/{len(chunks)} • Total Rewards: {len(currency_rewards)}")
            pages.append(embed)
            
        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)

    @guild_config.command(name="listrolerewards")
    @systems_ready
    async def guild_list_role_rewards(self, ctx):
        """List role rewards (paginated)"""
        role_rewards = await self.db.xp.get_all_xp_role_rewards(ctx.guild.id)
        
        if not role_rewards:
            await ctx.send("No role rewards configured.")
            return
            
        # Sort by level
        role_rewards.sort(key=lambda x: x[0])
        
        chunks = [role_rewards[i:i + 30] for i in range(0, len(role_rewards), 30)]
        pages = []
        
        for i, chunk in enumerate(chunks, 1):
            embed = discord.Embed(
                title=f"Role Rewards for {ctx.guild.name}",
                color=discord.Color.purple()
            )
            
            role_text = ""
            for level, role_id, remove in chunk:
                role = ctx.guild.get_role(role_id)
                role_name = role.mention if role else f"Deleted Role ({role_id})"
                action = "Remove" if remove else "Add"
                role_text += f"**Level {level}:** {action} {role_name}\n"
                
            embed.description = role_text
            embed.set_footer(text=f"Page {i}/{len(chunks)} • Total Rewards: {len(role_rewards)}")
            pages.append(embed)
            
        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            await menu(ctx, pages, DEFAULT_CONTROLS)
