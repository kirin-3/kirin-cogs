import discord
from redbot.core import commands, checks
from redbot.core.utils.menus import menu, DEFAULT_CONTROLS
from redbot.core.utils.chat_formatting import box, humanize_number
from typing import Optional

class AdminCommands:
    # Configuration commands
    @commands.group(name="unicornia", aliases=["uni"])
    async def unicornia_group(self, ctx):
        """Unicornia - Full-featured leveling and economy system"""
        pass

    @unicornia_group.group(name="migration")
    @checks.is_owner()
    async def migration_group(self, ctx):
        """Manage Nadeko database migration"""
        pass

    @migration_group.command(name="setpath")
    async def migration_setpath(self, ctx, path: str):
        """Set the path to the Nadeko database file"""
        await self.config.nadeko_db_path.set(path)
        
        # Update current instance
        if self.db:
            self.db.nadeko_db_path = path
            
        await ctx.send(f"✅ Nadeko DB path set to: `{path}`")

    @migration_group.command(name="run")
    async def migration_run(self, ctx):
        """Run the migration from Nadeko database
        
        This will migrate users, economy, XP, and other data from the configured
        Nadeko database file. This process may take some time.
        """
        nadeko_path = await self.config.nadeko_db_path()
        if not nadeko_path:
            await ctx.send("❌ No Nadeko DB path configured. Use `[p]unicornia migration setpath` first.")
            return
            
        await ctx.send(f"⏳ Starting migration from `{nadeko_path}`... Check console for progress.")
        try:
            # Re-initialize DB with correct path if needed
            if self.db and self.db.nadeko_db_path != nadeko_path:
                self.db.nadeko_db_path = nadeko_path
                
            await self.db.migrate_from_nadeko()
            await ctx.send("✅ Migration completed successfully!")
        except Exception as e:
            await ctx.send(f"❌ Migration failed: {e}")

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
        
        # Refresh cache
        if self.currency_generation:
            await self.currency_generation.refresh_config_cache()

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
    async def config_cmd(self, ctx, setting: str = None, *, value: str = None):
        """Configure Unicornia settings
        
        Run without arguments to view all settings.
        Run with setting name to view specific setting.
        Run with setting name and value to update.
        """
        valid_settings = [
            "currency_name", "currency_symbol", "xp_enabled", "economy_enabled",
            "gambling_enabled", "shop_enabled", "timely_amount", "timely_cooldown",
            "xp_per_message", "xp_cooldown", "currency_generation_enabled",
            "generation_chance", "generation_cooldown", "generation_min_amount",
            "generation_max_amount", "generation_has_password", "decay_percent",
            "decay_max_amount", "decay_min_threshold", "decay_hour_interval",
            "gambling_min_bet", "gambling_max_bet"
        ]
        
        if setting is None:
            # Construct display
            settings_display = []
            
            # Helper to get and format value
            async def get_val(key):
                val = await getattr(self.config, key)()
                if isinstance(val, bool):
                    return "Enabled" if val else "Disabled"
                if isinstance(val, (int, float)):
                     return humanize_number(val)
                return str(val)

            settings_display.append("[General]")
            settings_display.append(f"Currency Name:       {await self.config.currency_name()}")
            settings_display.append(f"Currency Symbol:     {await self.config.currency_symbol()}")
            settings_display.append(f"XP System:           {await get_val('xp_enabled')}")
            settings_display.append(f"Economy System:      {await get_val('economy_enabled')}")
            settings_display.append(f"Gambling System:     {await get_val('gambling_enabled')}")
            settings_display.append(f"Shop System:         {await get_val('shop_enabled')}")
            
            settings_display.append("\n[XP & Rewards]")
            settings_display.append(f"XP Per Message:      {await get_val('xp_per_message')}")
            settings_display.append(f"XP Cooldown:         {await get_val('xp_cooldown')}s")
            settings_display.append(f"Daily Amount:        {await get_val('timely_amount')}")
            settings_display.append(f"Daily Cooldown:      {await get_val('timely_cooldown')}h")

            settings_display.append("\n[Currency Generation]")
            settings_display.append(f"Enabled:             {await get_val('currency_generation_enabled')}")
            settings_display.append(f"Chance:              {await get_val('generation_chance')}")
            settings_display.append(f"Cooldown:            {await get_val('generation_cooldown')}s")
            settings_display.append(f"Min Amount:          {await get_val('generation_min_amount')}")
            settings_display.append(f"Max Amount:          {await get_val('generation_max_amount')}")
            settings_display.append(f"Password Required:   {await get_val('generation_has_password')}")

            settings_display.append("\n[Economy Decay]")
            settings_display.append(f"Decay Percent:       {await get_val('decay_percent')}")
            settings_display.append(f"Max Decay Amount:    {await get_val('decay_max_amount')}")
            settings_display.append(f"Min Threshold:       {await get_val('decay_min_threshold')}")
            settings_display.append(f"Interval:            {await get_val('decay_hour_interval')}h")
            
            settings_display.append("\n[Gambling]")
            settings_display.append(f"Min Bet:             {await get_val('gambling_min_bet')}")
            settings_display.append(f"Max Bet:             {await get_val('gambling_max_bet')}")

            await ctx.send(box("\n".join(settings_display), lang="ini"))
            return

        if setting not in valid_settings:
            await ctx.send(f"Invalid setting. Valid options: {', '.join(valid_settings)}")
            return
            
        if value is None:
            # Display single setting
            val = await getattr(self.config, setting)()
            if isinstance(val, (int, float)):
                val = humanize_number(val)
            await ctx.send(f"**{setting}**: {val}")
            return
        
        # Update setting
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
            
            # Refresh caches
            if self.currency_generation:
                await self.currency_generation.refresh_config_cache()
            if self.xp_system:
                await self.xp_system._init_config_cache()
                
        except ValueError:
            await ctx.send("❌ Invalid value type for this setting.")
        except Exception as e:
            await ctx.send(f"❌ Error updating setting: {e}")
    
    @unicornia_group.command(name="status")
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
        embed.add_field(name=f"{currency_symbol} {currency_name}", value=f"Symbol: {currency_symbol}\nName: {currency_name}", inline=True)
        
        timely_amount = await self.config.timely_amount()
        timely_cooldown = await self.config.timely_cooldown()
        embed.add_field(name="Daily Reward", value=f"{currency_symbol}{timely_amount} every {timely_cooldown}h", inline=True)
        
        await ctx.send(embed=embed)

    @unicornia_group.group(name="guild")
    @checks.admin()
    async def guild_config(self, ctx):
        """Guild-specific configuration"""
        pass
    
    @guild_config.group(name="xp")
    async def guild_xp_group(self, ctx):
        """Manage XP configuration"""
        pass

    @guild_xp_group.command(name="include")
    async def xp_include_channel(self, ctx, channel: discord.abc.GuildChannel):
        """Add a channel to the XP whitelist"""
        included = await self.config.guild(ctx.guild).xp_included_channels()
        if channel.id not in included:
            included.append(channel.id)
            await self.config.guild(ctx.guild).xp_included_channels.set(included)
            await ctx.send(f"✅ {channel.mention} added to XP whitelist.")
        else:
            await ctx.send(f"❌ {channel.mention} is already in the XP whitelist.")

    @guild_xp_group.command(name="exclude")
    async def xp_exclude_channel(self, ctx, channel: discord.abc.GuildChannel):
        """Remove a channel from the XP whitelist"""
        included = await self.config.guild(ctx.guild).xp_included_channels()
        if channel.id in included:
            included.remove(channel.id)
            await self.config.guild(ctx.guild).xp_included_channels.set(included)
            await ctx.send(f"✅ {channel.mention} removed from XP whitelist.")
        else:
            await ctx.send(f"❌ {channel.mention} is not in the XP whitelist.")

    @guild_xp_group.command(name="listchannels")
    async def xp_list_channels(self, ctx):
        """List all channels in the XP whitelist"""
        included = await self.config.guild(ctx.guild).xp_included_channels()
        if not included:
            await ctx.send("No channels are whitelisted for XP gain.")
            return

        channel_mentions = []
        for channel_id in included:
            channel = ctx.guild.get_channel(channel_id)
            if channel:
                channel_mentions.append(channel.mention)
            else:
                channel_mentions.append(f"<#{channel_id}> (Deleted)")
        
        await ctx.send(f"**XP Whitelisted Channels:**\n{', '.join(channel_mentions)}")
    
    @guild_config.command(name="rolereward")
    async def guild_role_reward(self, ctx, level: int, role: discord.Role, remove: bool = False):
        """Set a role reward for reaching a level (remove=True to remove role from user)"""
        if level < 1:
            await ctx.send("❌ Level must be at least 1.")
            return
        
        await self.db.xp.add_xp_role_reward(ctx.guild.id, level, role.id, remove)
        action = "removed from" if remove else "given to"
        await ctx.send(f"✅ Users reaching level {level} will have {role.mention} {action} them.")

    @guild_config.command(name="removerolereward")
    async def guild_remove_role_reward(self, ctx, level: int, role: discord.Role):
        """Remove a configured role reward"""
        await self.db.xp.remove_xp_role_reward(ctx.guild.id, level, role.id)
        await ctx.send(f"✅ Removed role reward {role.mention} at level {level}.")
    
    @guild_config.command(name="currencyreward")
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

    @unicornia_group.group(name="whitelist", aliases=["wl"])
    @checks.admin_or_permissions(manage_guild=True)
    async def whitelist_group(self, ctx):
        """Manage command and system usage restrictions"""
        pass

    # --- Command Whitelist ---
    @whitelist_group.group(name="command", aliases=["cmd"])
    async def wl_command_group(self, ctx):
        """Manage command whitelists"""
        pass

    @wl_command_group.command(name="add")
    async def wl_command_add(self, ctx, command_name: str, channel: discord.TextChannel = None):
        """Restrict a command to a channel (or current channel if none specified)"""
        channel = channel or ctx.channel
        
        # Verify command exists and belongs to Unicornia
        cmd = self.bot.get_command(command_name)
        if not cmd:
            await ctx.send(f"❌ Command `{command_name}` not found.")
            return
            
        if cmd.cog_name != self.qualified_name:
            await ctx.send(f"❌ You can only whitelist commands from {self.qualified_name} cog.")
            return
            
        async with self.config.guild(ctx.guild).command_whitelist() as whitelist:
            full_name = cmd.qualified_name
            if full_name not in whitelist:
                whitelist[full_name] = []
            
            if channel.id not in whitelist[full_name]:
                whitelist[full_name].append(channel.id)
                await ctx.send(f"✅ Command `{full_name}` is now allowed in {channel.mention}.")
            else:
                await ctx.send(f"❌ Command `{full_name}` is already allowed in {channel.mention}.")

    @wl_command_group.command(name="remove", aliases=["rm", "del"])
    async def wl_command_remove(self, ctx, command_name: str, channel: discord.TextChannel = None):
        """Remove a channel from command's whitelist"""
        channel = channel or ctx.channel
        
        # Verify command exists (optional)
        cmd = self.bot.get_command(command_name)
        full_name = cmd.qualified_name if cmd else command_name
            
        async with self.config.guild(ctx.guild).command_whitelist() as whitelist:
            if full_name in whitelist and channel.id in whitelist[full_name]:
                whitelist[full_name].remove(channel.id)
                # If list is empty, remove the key (back to "run everywhere" unless system restricted)
                if not whitelist[full_name]:
                    del whitelist[full_name]
                    await ctx.send(f"✅ Removed restrictions for `{full_name}` in {channel.mention}. It now runs based on system rules.")
                else:
                    await ctx.send(f"✅ Command `{full_name}` is no longer allowed in {channel.mention}.")
            else:
                await ctx.send(f"❌ Command `{full_name}` is not whitelisted in {channel.mention}.")

    @wl_command_group.command(name="list")
    async def wl_command_list(self, ctx):
        """List whitelisted commands"""
        whitelist = await self.config.guild(ctx.guild).command_whitelist()
        if not whitelist:
            await ctx.send("No commands are restricted (whitelisted).")
            return
            
        embed = discord.Embed(title="Whitelisted Commands", color=discord.Color.green())
        
        has_entries = False
        for cmd_name, channels in whitelist.items():
            if not channels:
                continue
            has_entries = True
            channel_mentions = []
            for cid in channels:
                ch = ctx.guild.get_channel(cid)
                if ch:
                    channel_mentions.append(ch.mention)
                else:
                    channel_mentions.append(f"<#{cid}>")
            
            embed.add_field(name=cmd_name, value=", ".join(channel_mentions), inline=False)
            
        if not has_entries:
            await ctx.send("No commands are restricted.")
        else:
            await ctx.send(embed=embed)

    # --- System Whitelist ---
    @whitelist_group.group(name="system", aliases=["sys"])
    async def wl_system_group(self, ctx):
        """Manage system whitelists"""
        pass
    
    @wl_system_group.command(name="add")
    async def wl_system_add(self, ctx, system: str, channel: discord.TextChannel = None):
        """Restrict an entire system to a channel"""
        channel = channel or ctx.channel
        system = system.lower()
        
        # Valid systems
        valid_systems = ["admin", "club", "currency", "economy", "gambling", "level", "nitro", "shop", "waifu"]
        if system not in valid_systems:
             await ctx.send(f"❌ Invalid system. Valid systems: {', '.join(valid_systems)}")
             return
            
        async with self.config.guild(ctx.guild).system_whitelist() as whitelist:
            if system not in whitelist:
                whitelist[system] = []
            
            if channel.id not in whitelist[system]:
                whitelist[system].append(channel.id)
                await ctx.send(f"✅ System `{system}` is now allowed in {channel.mention}.")
            else:
                await ctx.send(f"❌ System `{system}` is already allowed in {channel.mention}.")

    @wl_system_group.command(name="remove", aliases=["rm", "del"])
    async def wl_system_remove(self, ctx, system: str, channel: discord.TextChannel = None):
        """Remove a channel from system's whitelist"""
        channel = channel or ctx.channel
        system = system.lower()
        
        async with self.config.guild(ctx.guild).system_whitelist() as whitelist:
            if system in whitelist and channel.id in whitelist[system]:
                whitelist[system].remove(channel.id)
                # If list is empty, remove the key (runs everywhere)
                if not whitelist[system]:
                    del whitelist[system]
                    await ctx.send(f"✅ Removed restrictions for system `{system}` in {channel.mention}. It now runs everywhere.")
                else:
                    await ctx.send(f"✅ System `{system}` is no longer allowed in {channel.mention}.")
            else:
                await ctx.send(f"❌ System `{system}` is not whitelisted in {channel.mention}.")

    @wl_system_group.command(name="list")
    async def wl_system_list(self, ctx):
        """List whitelisted systems"""
        whitelist = await self.config.guild(ctx.guild).system_whitelist()
        if not whitelist:
            await ctx.send("No systems are restricted (whitelisted).")
            return
            
        embed = discord.Embed(title="Whitelisted Systems", color=discord.Color.green())
        
        has_entries = False
        for sys_name, channels in whitelist.items():
            if not channels:
                continue
            has_entries = True
            channel_mentions = []
            for cid in channels:
                ch = ctx.guild.get_channel(cid)
                if ch:
                    channel_mentions.append(ch.mention)
                else:
                    channel_mentions.append(f"<#{cid}>")
            
            embed.add_field(name=sys_name.title(), value=", ".join(channel_mentions), inline=False)
            
        if not has_entries:
            await ctx.send("No systems are restricted.")
        else:
            await ctx.send(embed=embed)

    @guild_config.command(name="listrolerewards")
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
