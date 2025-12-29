import discord
from redbot.core import commands, checks
from typing import Optional
from ..utils import systems_ready

class AdminCommands:
    # Configuration commands
    @commands.group(name="unicornia", aliases=["uni"])
    async def unicornia_group(self, ctx):
        """Unicornia - Full-featured leveling and economy system"""
        pass

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
    
    @guild_config.command(name="xpenabled")
    @systems_ready
    async def guild_xp_enabled(self, ctx, enabled: bool):
        """Enable/disable XP system for this guild"""
        await self.config.guild(ctx.guild).xp_enabled.set(enabled)
        await ctx.send(f"✅ XP system {'enabled' if enabled else 'disabled'} for this guild.")
    
    @guild_config.command(name="levelupmessages")
    @systems_ready
    async def guild_level_up_messages(self, ctx, enabled: bool):
        """Enable/disable level up messages for this guild"""
        await self.config.guild(ctx.guild).level_up_messages.set(enabled)
        await ctx.send(f"✅ Level up messages {'enabled' if enabled else 'disabled'} for this guild.")
    
    @guild_config.command(name="levelupchannel")
    @systems_ready
    async def guild_level_up_channel(self, ctx, channel: discord.TextChannel = None):
        """Set the channel for level up messages (leave empty for current channel)"""
        channel = channel or ctx.channel
        await self.config.guild(ctx.guild).level_up_channel.set(channel.id)
        await ctx.send(f"✅ Level up messages will be sent to {channel.mention}")
    
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
    async def guild_role_reward(self, ctx, level: int, role: discord.Role):
        """Set a role reward for reaching a level"""
        if level < 1:
            await ctx.send("❌ Level must be at least 1.")
            return
        
        role_rewards = await self.config.guild(ctx.guild).role_rewards()
        role_rewards[str(level)] = role.id
        await self.config.guild(ctx.guild).role_rewards.set(role_rewards)
        await ctx.send(f"✅ Users reaching level {level} will receive the {role.mention} role.")
    
    @guild_config.command(name="currencyreward")
    @systems_ready
    async def guild_currency_reward(self, ctx, level: int, amount: int):
        """Set a Slut points reward for reaching a level"""
        if level < 1:
            await ctx.send("❌ Level must be at least 1.")
            return
        
        if amount < 0:
            await ctx.send("❌ Amount must be positive.")
            return
        
        currency_rewards = await self.config.guild(ctx.guild).currency_rewards()
        currency_rewards[str(level)] = amount
        await self.config.guild(ctx.guild).currency_rewards.set(currency_rewards)
        currency_symbol = await self.config.currency_symbol()
        await ctx.send(f"✅ Users reaching level {level} will receive {currency_symbol}{amount:,}.")
