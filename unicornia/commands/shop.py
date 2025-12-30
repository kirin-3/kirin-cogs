import discord
from redbot.core import commands, checks
from typing import Optional

class BackgroundShopView(discord.ui.View):
    def __init__(self, ctx, backgrounds, user_owned, timeout=60):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.backgrounds = list(backgrounds.items()) # List of (key, data)
        self.user_owned = user_owned # Set of owned keys
        self.index = 0
        self.message = None
        self.update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This shop session is not for you.", ephemeral=True)
            return False
        return True

    def get_current_bg(self):
        return self.backgrounds[self.index]

    def update_buttons(self):
        self.children[0].disabled = (self.index == 0) # Previous
        self.children[2].disabled = (self.index == len(self.backgrounds) - 1) # Next
        
        key, data = self.get_current_bg()
        
        # Purchase button state
        price = data.get('price', -1)
        if key in self.user_owned:
            self.children[1].label = "Owned (Use)"
            self.children[1].style = discord.ButtonStyle.success
            self.children[1].disabled = False
        elif price == -1:
            self.children[1].label = "Unavailable"
            self.children[1].style = discord.ButtonStyle.secondary
            self.children[1].disabled = True
        else:
            self.children[1].label = f"Purchase ({price:,})"
            self.children[1].style = discord.ButtonStyle.primary
            self.children[1].disabled = False

    async def get_embed(self):
        key, data = self.get_current_bg()
        name = data.get('name', key)
        price = data.get('price', -1)
        desc = data.get('desc', '')
        url = data.get('url', '')
        
        price_text = "FREE" if price == 0 else f"{price:,} <:slut:686148402941001730>"
        if key in self.user_owned:
            price_text = "Owned"
            
        embed = discord.Embed(
            title=f"🖼️ XP Background: {name}",
            description=f"**Price:** {price_text}\n{desc}",
            color=discord.Color.blue()
        )
        if url:
            embed.set_image(url=url)
        
        embed.set_footer(text=f"Page {self.index + 1}/{len(self.backgrounds)} | Key: {key}")
        return embed

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(0, self.index - 1)
        self.update_buttons()
        embed = await self.get_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Purchase", style=discord.ButtonStyle.primary)
    async def buy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        key, data = self.get_current_bg()
        
        # Check if owned, if so, equip
        if key in self.user_owned:
             # Equip logic
            success = await self.ctx.cog.db.xp.set_active_xp_item(self.ctx.author.id, 1, key)
            if success:
                await interaction.response.send_message(f"✅ Equipped **{data.get('name', key)}**!", ephemeral=True)
            else:
                await interaction.response.send_message(f"❌ Failed to equip.", ephemeral=True)
            return

        # Buy logic
        price = data.get('price', -1)
        if price == -1:
            await interaction.response.send_message("❌ This item is unavailable.", ephemeral=True)
            return

        # Check balance
        user_balance = await self.ctx.cog.db.economy.get_user_currency(self.ctx.author.id)
        if user_balance < price:
             await interaction.response.send_message(f"❌ Insufficient funds. You need {price:,} <:slut:686148402941001730>.", ephemeral=True)
             return

        # Purchase
        success = await self.ctx.cog.db.xp.purchase_xp_item(self.ctx.author.id, 1, key, price)
        if success:
            self.user_owned.add(key)
            
            # Auto-equip
            await self.ctx.cog.db.xp.set_active_xp_item(self.ctx.author.id, 1, key)
            
            self.update_buttons()
            embed = await self.get_embed()
            # Update the main message to reflect "Owned" status
            await interaction.response.edit_message(embed=embed, view=self)
            await interaction.followup.send(f"✅ Purchased and equipped **{data.get('name', key)}**!", ephemeral=True)
        else:
             await interaction.response.send_message("❌ Purchase failed.", ephemeral=True)

    @discord.ui.button(label="Next ▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(len(self.backgrounds) - 1, self.index + 1)
        self.update_buttons()
        embed = await self.get_embed()
        await interaction.response.edit_message(embed=embed, view=self)

class ShopCommands:
    # Shop commands
    @commands.group(name="shop", aliases=["store"])
    async def shop_group(self, ctx):
        """Shop commands - Buy roles and items with currency"""
        pass
    
    @shop_group.command(name="list", aliases=["items", "view"])
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
                
                if item['additional_items']:
                    description += f"Items: {len(item['additional_items'])} additional items\n"
                
                embed.add_field(
                    name=f"#{item['index']} - {item['name']}",
                    value=description,
                    inline=True
                )
            
            embed.set_footer(text=f"Use '[p]shop buy <index>' to purchase an item")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving shop items: {e}")
    
    @shop_group.command(name="buy")
    async def shop_buy(self, ctx, index_or_id: int):
        """Buy a shop item by Index (recommended) or ID"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        try:
            success, message = await self.shop_system.purchase_item(ctx.author, ctx.guild.id, index_or_id)
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
    async def shop_info(self, ctx, index_or_id: int):
        """Get detailed information about a shop item (by Index or ID)"""
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        try:
            item = await self.shop_system.get_shop_item(ctx.guild.id, index_or_id)
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
            
            if item['additional_items']:
                items_text = "\n".join([f"• {item_text}" for _, item_text in item['additional_items']])
                embed.add_field(name="Additional Items", value=items_text[:1000], inline=False)
            
            embed.set_footer(text=f"Use '[p]shop buy {item['index']}' to purchase this item")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error retrieving item info: {e}")
    
    # Admin shop commands
    @shop_group.command(name="add")
    @commands.admin_or_permissions(manage_roles=True)
    async def shop_add(self, ctx, item_type: str, price: int, name: str, *, details: str = ""):
        """Add a new shop item (Admin only)
        
        Types: role, item, effect, other
        Usage:
        - [p]shop add role 1000 "VIP Role" @VIPRole
        - [p]shop add item 500 "Mystery Box"
        """
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        try:
            # Parse item type
            type_map = {
                'role': self.db.shop.SHOP_TYPE_ROLE,
                'item': self.db.shop.SHOP_TYPE_ITEM,
                'effect': self.db.shop.SHOP_TYPE_EFFECT,
                'other': self.db.shop.SHOP_TYPE_OTHER
            }
            
            if item_type.lower() not in type_map:
                await ctx.send("❌ Invalid item type. Use: role, item, effect, or other")
                return
            
            entry_type = type_map[item_type.lower()]
            
            # Get next index
            items = await self.shop_system.get_shop_items(ctx.guild.id)
            next_index = max([item['index'] for item in items], default=0) + 1
            
            role_id = None
            role_name = None
            
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
            
            # Add shop item
            item_id = await self.shop_system.add_shop_item(
                ctx.guild.id, next_index, price, name, ctx.author.id,
                entry_type, role_name, role_id, None, None
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
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error adding shop item: {e}")
    
    @shop_group.command(name="edit")
    @commands.admin_or_permissions(manage_roles=True)
    async def shop_edit(self, ctx, item_id: int, field: str, *, value: str):
        """Edit a shop item (Admin only)
        
        Fields:
        - name: Change item name
        - price: Change item price
        - type: Change type (role, item, effect, other)
        - role: Change role (mention or name) - For Role items
        - req: Change role requirement (mention, name, or 'none')
        
        Usage:
        `[p]shop edit 1 price 5000`
        `[p]shop edit 1 name Super VIP`
        `[p]shop edit 1 role @SuperVIP`
        """
        if not await self.config.shop_enabled():
            await ctx.send("❌ Shop system is disabled.")
            return
        
        try:
            # Get item
            item = await self.shop_system.get_shop_item(ctx.guild.id, item_id)
            if not item:
                await ctx.send("❌ Shop item not found.")
                return
            
            field = field.lower()
            updates = {}
            response_msg = ""
            
            if field == "price":
                try:
                    price = int(value)
                    if price < 0:
                        raise ValueError
                    updates['price'] = price
                    response_msg = f"Price updated to {price:,}"
                except ValueError:
                    await ctx.send("❌ Price must be a positive integer.")
                    return
            
            elif field == "name":
                if len(value) > 100:
                    await ctx.send("❌ Name is too long (max 100 chars).")
                    return
                updates['name'] = value
                response_msg = f"Name updated to **{value}**"
            
            elif field == "type":
                type_map = {
                    'role': self.db.shop.SHOP_TYPE_ROLE,
                    'item': self.db.shop.SHOP_TYPE_ITEM,
                    'effect': self.db.shop.SHOP_TYPE_EFFECT,
                    'other': self.db.shop.SHOP_TYPE_OTHER
                }
                if value.lower() not in type_map:
                    await ctx.send("❌ Invalid type. Options: role, item, effect, other")
                    return
                updates['entry_type'] = type_map[value.lower()]
                response_msg = f"Type updated to **{value.title()}**"
                
            elif field == "role":
                # Find role
                role = None
                if ctx.message.role_mentions:
                    role = ctx.message.role_mentions[0]
                else:
                    role = discord.utils.get(ctx.guild.roles, name=value.strip())
                
                if not role:
                    # Try by ID
                    try:
                        role = ctx.guild.get_role(int(value))
                    except ValueError:
                        pass
                
                if not role:
                    await ctx.send("❌ Role not found.")
                    return
                
                updates['role_id'] = role.id
                updates['role_name'] = role.name
                # Ensure type is role if it wasn't
                if item['type'] != self.db.shop.SHOP_TYPE_ROLE:
                    updates['entry_type'] = self.db.shop.SHOP_TYPE_ROLE
                    response_msg = f"Role updated to **{role.name}** (Type changed to Role)"
                else:
                    response_msg = f"Role updated to **{role.name}**"

            elif field in ["req", "requirement"]:
                if value.lower() == "none":
                    updates['role_requirement'] = None
                    response_msg = "Role requirement removed."
                else:
                    # Find role
                    role = None
                    if ctx.message.role_mentions:
                        role = ctx.message.role_mentions[0]
                    else:
                        role = discord.utils.get(ctx.guild.roles, name=value.strip())
                    
                    if not role:
                         # Try by ID
                        try:
                            role = ctx.guild.get_role(int(value))
                        except ValueError:
                            pass
                    
                    if not role:
                        await ctx.send("❌ Role not found.")
                        return
                    
                    updates['role_requirement'] = role.id
                    response_msg = f"Role requirement set to **{role.name}**"
            
            else:
                await ctx.send(f"❌ Invalid field. Available fields: name, price, type, role, req")
                return
            
            # Apply updates
            success = await self.shop_system.update_shop_item(ctx.guild.id, item['id'], **updates)
            
            if success:
                await ctx.send(f"✅ Shop item #{item['index']} updated: {response_msg}")
            else:
                await ctx.send("❌ Failed to update shop item.")
                
        except Exception as e:
            await ctx.send(f"❌ Error editing shop item: {e}")

    @shop_group.command(name="remove", aliases=["delete", "del"])
    @commands.admin_or_permissions(manage_roles=True)
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

    @commands.command(name="inventory", aliases=["inv", "bag"])
    async def show_inventory(self, ctx):
        """View your purchased items"""
        try:
            inventory = await self.shop_system.get_user_inventory(ctx.guild.id, ctx.author.id)
            
            if not inventory:
                await ctx.send("🎒 Your inventory is empty! Visit the shop with `[p]shop list`.")
                return
            
            embed = discord.Embed(
                title="🎒 Your Inventory",
                color=discord.Color.blue()
            )
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url if ctx.author.avatar else None)
            
            description = ""
            for item in inventory:
                item_emoji = self.shop_system.get_type_emoji(item['type'])
                description += f"**{item_emoji} {item['name']}** (x{item['quantity']})\n"
                description += f"Type: {self.shop_system.get_type_name(item['type'])} | ID: #{item['id']}\n\n"
            
            embed.description = description
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error loading inventory: {e}")

    # XP Shop commands
    @commands.group(name="xpshop", aliases=["xps"])
    async def xp_shop_group(self, ctx):
        """XP Shop - Buy custom backgrounds with currency"""
        pass
    
    @xp_shop_group.command(name="backgrounds", aliases=["bg", "bgs"])
    async def shop_backgrounds(self, ctx):
        """View available XP backgrounds"""
        
        try:
            backgrounds = self.xp_system.card_generator.get_available_backgrounds()
            if not backgrounds:
                await ctx.send("❌ No backgrounds configured.")
                return

            # Filter hidden items
            visible_backgrounds = {k: v for k, v in backgrounds.items() if not v.get('hidden', False)}
            
            if not visible_backgrounds:
                await ctx.send("❌ No backgrounds available.")
                return

            user_owned = await self.db.xp.get_user_xp_items(ctx.author.id, 1)  # 1 = Background
            owned_keys = {item[3] for item in user_owned}  # ItemKey
            
            view = BackgroundShopView(ctx, visible_backgrounds, owned_keys)
            embed = await view.get_embed()
            
            view.message = await ctx.send(embed=embed, view=view)
            
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
            
            bg_data = items[item_key]
            if bg_data.get('hidden', False):
                 await ctx.send(f"❌ Background `{item_key}` is not available for purchase.")
                 return

            if price == -1:
                await ctx.send(f"❌ Background `{item_key}` is no longer available for purchase.")
                return
            
            # Check balance
            user_balance = await self.db.economy.get_user_currency(ctx.author.id)
            if user_balance < price:
                await ctx.send(f"❌ Insufficient Slut points! You have {user_balance:,} <:slut:686148402941001730> but need {price:,} <:slut:686148402941001730>.")
                return

            # Attempt purchase (item_type_id = 1 for backgrounds)
            success = await self.db.xp.purchase_xp_item(ctx.author.id, 1, item_key, price)
            
            if success:
                item_name = items[item_key].get('name', item_key)
                price_text = "FREE" if price == 0 else f"{price:,} <:slut:686148402941001730>"
                
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
    async def shop_owned(self, ctx):
        """View your owned XP backgrounds"""
        
        try:
            owned_items = await self.db.xp.get_user_xp_items(ctx.author.id, 1)  # 1 = Background
            if not owned_items:
                await ctx.send("❌ You don't own any backgrounds yet. Use `[p]xpshop backgrounds` to see what's available!")
                return

            backgrounds = self.xp_system.card_generator.get_available_backgrounds()
            owned_keys = {item[3] for item in owned_items}  # ItemKey
            
            # Filter backgrounds to only show owned ones
            owned_backgrounds = {k: v for k, v in backgrounds.items() if k in owned_keys}
            
            # Use the interactive view
            view = BackgroundShopView(ctx, owned_backgrounds, owned_keys)
            embed = await view.get_embed()
            embed.title = "🎒 Your XP Backgrounds" # Override title
            
            view.message = await ctx.send(embed=embed, view=view)
            
        except Exception as e:
            await ctx.send(f"❌ Error loading owned backgrounds: {e}")
    
    @xp_shop_group.command(name="reload")
    @commands.is_owner()
    async def shop_reload_config(self, ctx):
        """Reload XP shop configuration (Owner only)"""
        try:
            await self.xp_system.card_generator._load_xp_config()
            await ctx.send("✅ XP shop configuration reloaded successfully!")
        except Exception as e:
            await ctx.send(f"❌ Error reloading configuration: {e}")
    
    @xp_shop_group.command(name="give")
    @commands.is_owner()
    async def shop_give_bg(self, ctx, user: discord.Member, item_key: str):
        """Give an XP background to a user (Owner only)"""
        try:
            items = self.xp_system.card_generator.get_available_backgrounds()
            if item_key not in items:
                await ctx.send(f"❌ Background `{item_key}` not found.")
                return

            success = await self.db.xp.give_xp_item(user.id, 1, item_key) # 1 = Background
            
            if success:
                item_name = items[item_key].get('name', item_key)
                await ctx.send(f"✅ Gave **{item_name}** to {user.mention}!")
            else:
                await ctx.send(f"❌ {user.mention} already owns `{item_key}`.")
                
        except Exception as e:
             await ctx.send(f"❌ Error giving background: {e}")

