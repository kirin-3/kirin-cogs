import discord
from redbot.core import commands, checks
from typing import Optional
from ..utils import systems_ready

class ShopCommands:
    # Shop commands
    @commands.group(name="shop", aliases=["store"])
    async def shop_group(self, ctx):
        """Shop commands - Buy roles and items with currency"""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    
    @shop_group.command(name="list", aliases=["items", "view"])
    @systems_ready
    async def shop_list(self, ctx):
        """View all available shop items"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        
        try:
            items = await self.shop_system.get_shop_items(ctx.guild.id)
            if not items:
                await ctx.send("🛒 The shop is empty! Admins can add items with `[p]shop add`.")
                return
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title="🛒 Shop Items",
                description="Purchase items with your Slut points!",
                color=discord.Color.green()
            )
            
            for item in items[:10]:  # Limit to 10 items per page
                item_type = self.shop_system.get_type_name(item['type'])
                emoji = self.shop_system.get_type_emoji(item['type'])
                
                description = f"**{emoji} {item['name']}** - {currency_symbol}{item['price']:,}\n"
                description += f"Type: {item_type}\n"
                
                if item['type'] == self.db.shop.SHOP_TYPE_ROLE and item['role_name']:
                    description += f"Role: {item['role_name']}\n"
                elif item['type'] == self.db.shop.SHOP_TYPE_COMMAND and item['command']:
                    description += f"Command: `{item['command']}`\n"
                
                if item['additional_items']:
                    description += f"Items: {len(item['additional_items'])} additional items\n"
                
                embed.add_field(
                    name=f"#{item['index']} - {item['name']}",
                    value=description,
                    inline=True
                )
            
            embed.set_footer(text=f"Use '[p]shop buy <item_id>' to purchase an item")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving shop items: {e}")
    
    @shop_group.command(name="buy")
    @systems_ready
    async def shop_buy(self, ctx, item_id: int):
        """Buy a shop item"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        
        try:
            success, message = await self.shop_system.purchase_item(ctx.author, ctx.guild.id, item_id)
            if success:
                currency_symbol = await self.config.currency_symbol()
                # Replace currency in message if it comes from system with generic term
                message = message.replace("currency", "Slut points")
                embed = discord.Embed(
                    title="✅ Purchase Successful!",
                    description=message,
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="💡 Tip",
                    value="Use `[p]shop list` to see all available items!",
                    inline=False
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send(f"❌ {message}")
                
        except Exception as e:
            await ctx.send(f"❌ Error purchasing item: {e}")
    
    @shop_group.command(name="info")
    @systems_ready
    async def shop_info(self, ctx, item_id: int):
        """Get detailed information about a shop item"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        
        try:
            item = await self.shop_system.get_shop_item(ctx.guild.id, item_id)
            if not item:
                await ctx.send("❌ Shop item not found.")
                return
            
            currency_symbol = await self.config.currency_symbol()
            item_type = self.shop_system.get_type_name(item['type'])
            emoji = self.shop_system.get_type_emoji(item['type'])
            
            embed = discord.Embed(
                title=f"{emoji} {item['name']}",
                description=f"**Price:** {currency_symbol}{item['price']:,}\n**Type:** {item_type}",
                color=discord.Color.blue()
            )
            
            if item['type'] == self.db.shop.SHOP_TYPE_ROLE:
                if item['role_name']:
                    embed.add_field(name="Role", value=item['role_name'], inline=True)
                if item['role_requirement']:
                    req_role = ctx.guild.get_role(item['role_requirement'])
                    if req_role:
                        embed.add_field(name="Requirement", value=f"Must have {req_role.name}", inline=True)
            
            elif item['type'] == self.db.shop.SHOP_TYPE_COMMAND:
                if item['command']:
                    embed.add_field(name="Command", value=f"`{item['command']}`", inline=True)
            
            if item['additional_items']:
                items_text = "\n".join([f"• {item_text}" for _, item_text in item['additional_items']])
                embed.add_field(name="Additional Items", value=items_text[:1000], inline=False)
            
            embed.set_footer(text=f"Use '[p]shop buy {item_id}' to purchase this item")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving item info: {e}")
    
    # Admin shop commands
    @shop_group.command(name="add")
    @commands.admin_or_permissions(manage_roles=True)
    @systems_ready
    async def shop_add(self, ctx, item_type: str, price: int, name: str, *, details: str = ""):
        """Add a new shop item (Admin only)
        
        Types: role, command, effect, other
        Usage: [p]shop add role 1000 "VIP Role" @VIPRole
        """
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        try:
            # Parse item type
            type_map = {
                'role': self.db.shop.SHOP_TYPE_ROLE,
                'command': self.db.shop.SHOP_TYPE_COMMAND,
                'effect': self.db.shop.SHOP_TYPE_EFFECT,
                'other': self.db.shop.SHOP_TYPE_OTHER
            }
            
            if item_type.lower() not in type_map:
                await ctx.send("❌ Invalid item type. Use: role, command, effect, or other")
                return
            
            entry_type = type_map[item_type.lower()]
            
            # Get next index
            items = await self.shop_system.get_shop_items(ctx.guild.id)
            next_index = max([item['index'] for item in items], default=0) + 1
            
            role_id = None
            role_name = None
            command = None
            
            if entry_type == self.db.shop.SHOP_TYPE_ROLE:
                # Parse role from details
                if not details:
                    await ctx.send("❌ Please specify a role for role items. Usage: `[p]shop add role 1000 \"VIP Role\" @VIPRole`")
                    return
                
                # Try to find role mention or name
                role = None
                if ctx.message.role_mentions:
                    role = ctx.message.role_mentions[0]
                else:
                    # Try to find by name
                    role = discord.utils.get(ctx.guild.roles, name=details.strip())
                
                if not role:
                    await ctx.send("❌ Role not found. Please mention the role or use the exact name.")
                    return
                
                role_id = role.id
                role_name = role.name
            
            elif entry_type == self.db.shop.SHOP_TYPE_COMMAND:
                command = details.strip()
                if not command:
                    await ctx.send("❌ Please specify a command for command items.")
                    return
            
            # Add shop item
            item_id = await self.shop_system.add_shop_item(
                ctx.guild.id, next_index, price, name, ctx.author.id,
                entry_type, role_name, role_id, None, command
            )
            
            currency_symbol = await self.config.currency_symbol()
            embed = discord.Embed(
                title="✅ Shop Item Added!",
                description=f"**{name}** - {currency_symbol}{price:,}",
                color=discord.Color.green()
            )
            embed.add_field(name="Type", value=item_type.title(), inline=True)
            embed.add_field(name="ID", value=str(item_id), inline=True)
            embed.add_field(name="Index", value=str(next_index), inline=True)
            
            if role_name:
                embed.add_field(name="Role", value=role_name, inline=True)
            if command:
                embed.add_field(name="Command", value=f"`{command}`", inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error adding shop item: {e}")
    
    @shop_group.command(name="remove", aliases=["delete", "del"])
    @commands.admin_or_permissions(manage_roles=True)
    @systems_ready
    async def shop_remove(self, ctx, item_id: int):
        """Remove a shop item (Admin only)"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        try:
            # Get item info before deleting
            item = await self.shop_system.get_shop_item(ctx.guild.id, item_id)
            if not item:
                await ctx.send("❌ Shop item not found.")
                return
            
            success = await self.shop_system.delete_shop_item(ctx.guild.id, item_id)
            if success:
                await ctx.send(f"✅ Removed shop item: **{item['name']}**")
            else:
                await ctx.send("❌ Failed to remove shop item.")
                
        except Exception as e:
            await ctx.send(f"❌ Error removing shop item: {e}")

    # XP Shop commands
    @commands.group(name="xpshop", aliases=["xps"])
    async def xp_shop_group(self, ctx):
        """XP Shop - Buy custom backgrounds with currency"""
        if ctx.invoked_subcommand is None:
            import logging
            log = logging.getLogger("red.unicornia.debug")
            log.info(f"XPShop group invoked without subcommand by {ctx.author}. Sending help manually.")
            await ctx.send_help(ctx.command)
    
    @xp_shop_group.command(name="backgrounds", aliases=["bg", "bgs"])
    @systems_ready
    async def shop_backgrounds(self, ctx):
        """View available XP backgrounds"""
        
        try:
            backgrounds = self.xp_system.card_generator.get_available_backgrounds()
            user_owned = await self.db.xp.get_user_xp_items(ctx.author.id, 1)  # 1 = Background
            owned_keys = {item[3] for item in user_owned}  # ItemKey
            
            embed = discord.Embed(
                title="🖼️ XP Backgrounds Shop",
                description="Purchase backgrounds with your Slut points!",
                color=discord.Color.blue()
            )
            
            for key, bg_data in backgrounds.items():
                name = bg_data.get('name', key)
                price = bg_data.get('price', -1)
                desc = bg_data.get('desc', '')
                
                if price == -1:
                    continue  # Skip removed items
                
                owned_text = " ✅ **OWNED**" if key in owned_keys else ""
                price_text = "FREE" if price == 0 else f"{price:,} 🪙"
                
                embed.add_field(
                    name=f"{name}{owned_text}",
                    value=f"Price: {price_text}\n{desc}",
                    inline=True
                )
            
            user_currency = await self.db.economy.get_user_currency(ctx.author.id)
            embed.set_footer(text=f"Your Slut points: {user_currency:,} <:slut:686148402941001730>")
            
            await ctx.send(embed=embed)
            
        except (OSError, IOError) as e:
            import logging
            log = logging.getLogger("red.unicornia")
            log.error(f"Error loading XP backgrounds: {e}")
            await ctx.send("❌ Error loading backgrounds. Please check the configuration file.")
        except Exception as e:
            import logging
            log = logging.getLogger("red.unicornia")
            log.error(f"Unexpected error loading backgrounds: {e}", exc_info=True)
            await ctx.send("❌ An unexpected error occurred while loading backgrounds.")
    
    @xp_shop_group.command(name="buy")
    @systems_ready
    async def shop_buy_bg(self, ctx, item_key: str):
        """Buy an XP background
        
        Usage: 
        - `[p]xpshop buy default` - Buy default background
        - `[p]xpshop buy shadow` - Buy shadow background
        """
        
        try:
            # Get background info
            items = self.xp_system.card_generator.get_available_backgrounds()
            price = self.xp_system.card_generator.get_background_price(item_key)
            
            if item_key not in items:
                await ctx.send(f"❌ Background `{item_key}` not found.")
                return
            
            if price == -1:
                await ctx.send(f"❌ Background `{item_key}` is no longer available for purchase.")
                return
            
            # Attempt purchase (item_type_id = 1 for backgrounds)
            success = await self.db.xp.purchase_xp_item(ctx.author.id, 1, item_key, price)
            
            if success:
                item_name = items[item_key].get('name', item_key)
                price_text = "FREE" if price == 0 else f"{price:,} 🪙"
                
                # Auto-equip logic
                equip_success = await self.db.xp.set_active_xp_item(ctx.author.id, 1, item_key)
                
                msg = f"✅ Successfully purchased **{item_name}** for {price_text}!"
                if equip_success:
                    msg += f"\n🌟 Auto-equipped **{item_name}** as your new background!"
                else:
                    msg += f"\n(Tip: Use `[p]xpshop use {item_key}` to equip it)"
                    
                await ctx.send(msg)
            else:
                # Check why it failed
                if await self.db.xp.user_owns_xp_item(ctx.author.id, 1, item_key):
                    await ctx.send(f"❌ You already own this background!")
                else:
                    user_currency = await self.db.economy.get_user_currency(ctx.author.id)
                    await ctx.send(f"❌ Insufficient Slut points! You have {user_currency:,} <:slut:686148402941001730> but need {price:,} <:slut:686148402941001730>.")
            
        except Exception as e:
            await ctx.send(f"❌ Error processing purchase: {e}")
    
    @xp_shop_group.command(name="use")
    @systems_ready
    async def shop_use(self, ctx, item_key: str):
        """Set an XP background as active
        
        Usage: 
        - `[p]xpshop use default` - Use default background
        - `[p]xpshop use shadow` - Use shadow background (must own it first)
        """
        
        try:
            # Check if user owns the background
            if not await self.db.xp.user_owns_xp_item(ctx.author.id, 1, item_key):
                await ctx.send(f"❌ You don't own the background `{item_key}`. Purchase it first with `[p]xpshop buy {item_key}`.")
                return
            
            # Set as active
            success = await self.db.xp.set_active_xp_item(ctx.author.id, 1, item_key)
            
            if success:
                backgrounds = self.xp_system.card_generator.get_available_backgrounds()
                item_name = backgrounds.get(item_key, {}).get('name', item_key)
                await ctx.send(f"✅ Now using **{item_name}** as your XP background!")
            else:
                await ctx.send(f"❌ Failed to set background. Make sure you own `{item_key}`.")
                
        except Exception as e:
            await ctx.send(f"❌ Error setting background: {e}")
    
    @xp_shop_group.command(name="owned", aliases=["inventory", "inv"])
    @systems_ready
    async def shop_owned(self, ctx):
        """View your owned XP backgrounds"""
        
        try:
            owned_items = await self.db.xp.get_user_xp_items(ctx.author.id, 1)  # 1 = Background
            backgrounds = self.xp_system.card_generator.get_available_backgrounds()
            
            if not owned_items:
                await ctx.send("❌ You don't own any backgrounds yet. Use `[p]xpshop backgrounds` to see what's available!")
                return
            
            embed = discord.Embed(
                title="🎒 Your XP Backgrounds",
                description="Backgrounds you own",
                color=discord.Color.green()
            )
            
            active_background = await self.db.xp.get_active_xp_item(ctx.author.id, 1)
            
            for item in owned_items:
                item_key = item[3]  # ItemKey from database
                bg_data = backgrounds.get(item_key, {})
                name = bg_data.get('name', item_key)
                desc = bg_data.get('desc', '')
                
                status = " 🌟 **ACTIVE**" if item_key == active_background else ""
                
                embed.add_field(
                    name=f"{name}{status}",
                    value=f"Key: `{item_key}`\n{desc}" if desc else f"Key: `{item_key}`",
                    inline=True
                )
            
            embed.set_footer(text=f"Use '[p]xpshop use <key>' to change your active background")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error loading owned backgrounds: {e}")
    
    @xp_shop_group.command(name="reload")
    @commands.is_owner()
    @systems_ready
    async def shop_reload_config(self, ctx):
        """Reload XP shop configuration (Owner only)"""
        try:
            await self.xp_system.card_generator._load_xp_config()
            await ctx.send("✅ XP shop configuration reloaded successfully!")
        except Exception as e:
            await ctx.send(f"❌ Error reloading configuration: {e}")
    
    @xp_shop_group.command(name="config")
    @commands.is_owner()
    @systems_ready
    async def shop_config_info(self, ctx):
        """Show XP shop configuration file location (Owner only)"""
        import os
        config_path = os.path.join(self.xp_system.card_generator.cog_dir, "xp_config.yml")
        embed = discord.Embed(
            title="🔧 XP Shop Configuration",
            description=f"Configuration file location:\n`{config_path}`",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="How to add/edit backgrounds:",
            value="1. Edit the `xp_config.yml` file\n2. Add new backgrounds under `shop.bgs`\n3. Use `[p]xpshop reload` to apply changes",
            inline=False
        )
        embed.add_field(
            name="Background format:",
            value="```yaml\nkey_name:\n  name: Display Name\n  price: 10000\n  url: https://your-image-url.com/image.gif\n  desc: Optional description```",
            inline=False
        )
        embed.add_field(
            name="Available Commands:",
            value="`[p]xpshop backgrounds` - View all backgrounds\n`[p]xpshop buy <key>` - Purchase a background\n`[p]xpshop use <key>` - Set active background\n`[p]xpshop owned` - View your inventory",
            inline=False
        )
        embed.add_field(
            name="Note:",
            value="All users start with the 'default' background. Purchase backgrounds with Slut points, then use `[p]xpshop use <key>` to activate them!",
            inline=False
        )
        await ctx.send(embed=embed)
