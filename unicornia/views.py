import discord
from discord import ui
from redbot.core.utils.chat_formatting import humanize_number
from redbot.core.utils.views import ConfirmView

class RockPaperScissorsView(ui.View):
    def __init__(self, user: discord.abc.User, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.user = user
        self.choice = None
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.stop()

    @ui.button(emoji="🪨", style=discord.ButtonStyle.primary)
    async def rock(self, interaction: discord.Interaction, button: ui.Button):
        self.choice = "rock"
        await interaction.response.defer()
        self.stop()

    @ui.button(emoji="📄", style=discord.ButtonStyle.primary)
    async def paper(self, interaction: discord.Interaction, button: ui.Button):
        self.choice = "paper"
        await interaction.response.defer()
        self.stop()

    @ui.button(emoji="✂️", style=discord.ButtonStyle.primary)
    async def scissors(self, interaction: discord.Interaction, button: ui.Button):
        self.choice = "scissors"
        await interaction.response.defer()
        self.stop()

class CoinFlipView(ui.View):
    def __init__(self, user: discord.abc.User, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.user = user
        self.choice = None
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("This isn't your coin flip!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.stop()

    @ui.button(label="Heads", emoji="🪙", style=discord.ButtonStyle.success)
    async def heads(self, interaction: discord.Interaction, button: ui.Button):
        self.choice = "Heads"
        await interaction.response.defer()
        self.stop()

    @ui.button(label="Tails", emoji="🦅", style=discord.ButtonStyle.primary)
    async def tails(self, interaction: discord.Interaction, button: ui.Button):
        self.choice = "Tails"
        await interaction.response.defer()
        self.stop()

class ApplicantProcessView(ui.View):
    def __init__(self, ctx, applicants: list[dict], club_system):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.applicants = applicants
        self.club_system = club_system
        self.selected_user_id = None
        self.message = None
        
        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.stop()

    def update_components(self):
        self.clear_items()
        
        if not self.applicants:
            self.stop()
            return

        # Select Menu
        options = []
        for app in self.applicants[:25]:
            label = app['username']
            # Ensure label isn't too long/empty
            if not label: label = "Unknown User"
            
            options.append(discord.SelectOption(
                label=label[:100],
                value=str(app['user_id']),
                description=f"XP: {app['total_xp']:,}"
            ))
        
        select = ui.Select(placeholder="Select an applicant to process...", options=options, min_values=1, max_values=1)
        
        async def select_callback(interaction: discord.Interaction):
            self.selected_user_id = int(select.values[0])
            # Enable buttons
            for child in self.children:
                if isinstance(child, ui.Button):
                    child.disabled = False
            
            await interaction.response.edit_message(view=self)
            
        select.callback = select_callback
        self.add_item(select)
        
        # Buttons
        accept_btn = ui.Button(label="Accept", style=discord.ButtonStyle.success, disabled=True)
        reject_btn = ui.Button(label="Reject", style=discord.ButtonStyle.danger, disabled=True)
        
        async def accept_callback(interaction: discord.Interaction):
            await self.process_application(interaction, True)
            
        async def reject_callback(interaction: discord.Interaction):
            await self.process_application(interaction, False)
            
        accept_btn.callback = accept_callback
        reject_btn.callback = reject_callback
        
        self.add_item(accept_btn)
        self.add_item(reject_btn)

    async def process_application(self, interaction: discord.Interaction, accepted: bool):
        applicant = next((a for a in self.applicants if a['user_id'] == self.selected_user_id), None)
        if not applicant:
            await interaction.response.send_message("Applicant selection invalid or user already processed.", ephemeral=True)
            self.update_components()
            await interaction.edit_original_response(view=self)
            return

        await interaction.response.defer()
        
        name = applicant['username']
        if accepted:
            success, msg = await self.club_system.accept_application(self.ctx.author, name)
        else:
            success, msg = await self.club_system.reject_application(self.ctx.author, name)
            
        if success:
            # Remove from list
            self.applicants = [a for a in self.applicants if a['user_id'] != self.selected_user_id]
            self.selected_user_id = None
            
            if not self.applicants:
                 await interaction.followup.send(f"✅ Action complete: {msg}\nNo more applicants remaining.", ephemeral=True)
                 self.clear_items()
                 await interaction.edit_original_response(content="✅ All applicants processed.", view=None)
                 self.stop()
            else:
                 await interaction.followup.send(f"✅ Action complete: {msg}", ephemeral=True)
                 self.update_components()
                 await interaction.edit_original_response(view=self)
        else:
            await interaction.followup.send(f"❌ Error: {msg}", ephemeral=True)

class ShopBrowserView(ui.View):
    def __init__(self, ctx, items: list[dict], shop_system):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.all_items = items
        self.shop_system = shop_system
        
        # Filter state
        self.current_category = -1 # -1 = All
        self.filtered_items = self.all_items
        
        # Pagination state
        self.current_page = 0
        self.items_per_page = 10
        
        self.message = None
        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This shop session is not for you.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.stop()

    def filter_items(self):
        if self.current_category == -1:
            self.filtered_items = self.all_items
        else:
            self.filtered_items = [i for i in self.all_items if i['type'] == self.current_category]
        
        # Reset page if out of bounds
        max_pages = max(0, (len(self.filtered_items) - 1) // self.items_per_page)
        if self.current_page > max_pages:
            self.current_page = 0

    def get_current_page_items(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        return self.filtered_items[start:end]

    async def get_embed(self):
        currency_symbol = await self.ctx.cog.config.currency_symbol()
        
        embed = discord.Embed(
            title="🛒 Shop Browser",
            description=f"Purchase items with your {currency_symbol}!",
            color=discord.Color.green()
        )
        
        page_items = self.get_current_page_items()
        
        if not page_items:
            embed.description = "No items found in this category."
        
        for item in page_items:
            item_type = self.shop_system.get_type_name(item['type'])
            emoji = self.shop_system.get_type_emoji(item['type'])
            
            price_text = f"{currency_symbol}{item['price']:,}"
            desc = f"**Type:** {item_type}\n**Price:** {price_text}"
            
            if item['type'] == self.shop_system.db.shop.SHOP_TYPE_ROLE and item['role_name']:
                desc += f"\n**Role:** {item['role_name']}"
                if item['role_requirement']:
                    req_role = self.ctx.guild.get_role(item['role_requirement'])
                    req_name = req_role.name if req_role else "Unknown Role"
                    desc += f"\n**Requires:** {req_name}"
            
            if item['additional_items']:
                desc += f"\n**Includes:** {len(item['additional_items'])} items"
                
            embed.add_field(
                name=f"{emoji} #{item['index']} - {item['name']}",
                value=desc,
                inline=True
            )
            
        total_pages = (len(self.filtered_items) - 1) // self.items_per_page + 1
        embed.set_footer(text=f"Page {self.current_page + 1}/{total_pages} • Total Items: {len(self.filtered_items)}")
        return embed

    def update_components(self):
        self.clear_items()
        
        # 1. Category Select
        # We need to map category IDs to names. Using logic from ShopSystem
        # DB Types: 0=Role, 1=Command(Deprecated), 2=Effect, 3=Other, 4=Item
        # Accessing via shop_system.db.shop constants for consistency
        shop_db = self.shop_system.db.shop
        categories = [
            ("All Categories", -1, "🌐"),
            ("Roles", shop_db.SHOP_TYPE_ROLE, "🎭"), # 0
            ("Items", shop_db.SHOP_TYPE_ITEM, "🎒"), # 4
            ("Effects", shop_db.SHOP_TYPE_EFFECT, "✨"), # 2
            ("Other", shop_db.SHOP_TYPE_OTHER, "📦") # 3
        ]
        
        cat_options = []
        for name, value, emoji in categories:
            cat_options.append(discord.SelectOption(
                label=name,
                value=str(value),
                emoji=emoji,
                default=(value == self.current_category)
            ))
            
        cat_select = ui.Select(
            placeholder="Filter by category...",
            options=cat_options,
            row=0,
            custom_id="category_select"
        )
        
        async def cat_callback(interaction: discord.Interaction):
            self.current_category = int(cat_select.values[0])
            self.current_page = 0
            self.filter_items()
            self.update_components()
            embed = await self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            
        cat_select.callback = cat_callback
        self.add_item(cat_select)
        
        # 2. Buy Select (if items exist)
        page_items = self.get_current_page_items()
        if page_items:
            buy_options = []
            for item in page_items:
                label = f"#{item['index']} {item['name']}"
                price_str = f"{item['price']:,}"
                buy_options.append(discord.SelectOption(
                    label=label[:100],
                    value=str(item['index']), # Using index as value for purchase command
                    description=f"Price: {price_str}",
                    emoji=self.shop_system.get_type_emoji(item['type'])
                ))
            
            buy_select = ui.Select(
                placeholder="Select an item to buy...",
                options=buy_options,
                row=1,
                custom_id="buy_select"
            )
            
            async def buy_callback(interaction: discord.Interaction):
                index = int(buy_select.values[0])
                # We need to find the item ID (not index) or pass index to purchase_item
                # shop_system.purchase_item takes (user, guild_id, index_or_id)
                # It handles index lookup internally.
                
                await interaction.response.defer()
                
                success, msg = await self.shop_system.purchase_item(self.ctx.author, self.ctx.guild.id, index)
                
                if success:
                    # Refresh currency symbol just in case
                    currency_symbol = await self.ctx.cog.config.currency_symbol()
                    msg = msg.replace("currency", currency_symbol) # Generic replace if needed
                    await interaction.followup.send(f"✅ {msg}", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ {msg}", ephemeral=True)
                    
            buy_select.callback = buy_callback
            self.add_item(buy_select)
            
        # 3. Pagination Buttons
        total_pages = (len(self.filtered_items) - 1) // self.items_per_page + 1
        
        prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.secondary, row=2, disabled=(self.current_page == 0))
        next_btn = ui.Button(label="▶️", style=discord.ButtonStyle.secondary, row=2, disabled=(self.current_page >= total_pages - 1))
        
        async def prev_callback(interaction: discord.Interaction):
            self.current_page = max(0, self.current_page - 1)
            self.update_components()
            embed = await self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            
        async def next_callback(interaction: discord.Interaction):
            self.current_page = min(total_pages - 1, self.current_page + 1)
            self.update_components()
            embed = await self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            
        prev_btn.callback = prev_callback
        next_btn.callback = next_callback
        
        self.add_item(prev_btn)
        
        # Indicator Button (disabled)
        indicator = ui.Button(label=f"Page {self.current_page + 1}/{max(1, total_pages)}", style=discord.ButtonStyle.secondary, disabled=True, row=2)
        self.add_item(indicator)
        
        self.add_item(next_btn)

class LeaderboardView(ui.View):
    def __init__(self, ctx, entries: list[tuple[int, int]], user_position: int = None, currency_symbol: str = "$", title: str = None, formatter=None):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.entries = entries # list of (user_id, balance)
        self.user_position = user_position # 0-based index in the entries list
        self.currency_symbol = currency_symbol
        self.title = title or f"<:slut:686148402941001730> Economy Leaderboard"
        self.formatter = formatter
        
        self.current_page = 0
        self.items_per_page = 10
        self.message = None
        
        # Init page based on user position if user called it to see themselves?
        # Usually starts at 0. Jump to me handles the rest.
        
        self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Allow anyone to use pagination, but Jump to Me logic is specific to viewing self
        # Actually standard practice is only author controls view, but for leaderboards public nav is often nice.
        # But for simplicity let's restrict to author.
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This leaderboard is not for you.", ephemeral=True)
            return False
        return True
        
    async def on_timeout(self):
        if self.message:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.stop()

    def get_current_page_entries(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        return self.entries[start:end], start

    async def get_embed(self):
        embed = discord.Embed(
            title=self.title,
            color=discord.Color.gold()
        )
        
        page_entries, start_index = self.get_current_page_entries()
        
        description = ""
        for i, (user_id, balance) in enumerate(page_entries):
            rank = start_index + i + 1
            member = self.ctx.guild.get_member(user_id)
            username = member.display_name if member else f"User ID: {user_id}"
            
            rank_str = f"**{rank}.**"
            if rank == 1: rank_str = "🥇"
            elif rank == 2: rank_str = "🥈"
            elif rank == 3: rank_str = "🥉"
            
            # Highlight caller
            if self.formatter:
                line = self.formatter(rank, rank_str, member, user_id, balance)
            else:
                line = f"{rank_str} **{username}**\n{self.currency_symbol}{balance:,}\n"
            
            if self.user_position is not None and rank == (self.user_position + 1):
                line = f"👉 {line}"
                
            description += line
            
        embed.description = description
        
        total_pages = (len(self.entries) - 1) // self.items_per_page + 1
        embed.set_footer(text=f"Page {self.current_page + 1}/{total_pages} • Total: {len(self.entries)}")
        
        if self.user_position is not None:
             embed.set_footer(text=f"{embed.footer.text} • You are #{self.user_position + 1}")
             
        return embed

    def update_components(self):
        self.clear_items()
        
        total_pages = (len(self.entries) - 1) // self.items_per_page + 1
        
        # Navigation
        prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
        next_btn = ui.Button(label="▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= total_pages - 1))
        
        async def prev_callback(interaction: discord.Interaction):
            self.current_page = max(0, self.current_page - 1)
            self.update_components()
            embed = await self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            
        async def next_callback(interaction: discord.Interaction):
            self.current_page = min(total_pages - 1, self.current_page + 1)
            self.update_components()
            embed = await self.get_embed()
            await interaction.response.edit_message(embed=embed, view=self)
            
        prev_btn.callback = prev_callback
        next_btn.callback = next_callback
        
        self.add_item(prev_btn)
        
        # Jump to Me
        jump_btn = ui.Button(label="Jump to Me", style=discord.ButtonStyle.primary, disabled=(self.user_position is None))
        
        async def jump_callback(interaction: discord.Interaction):
            if self.user_position is not None:
                self.current_page = self.user_position // self.items_per_page
                self.update_components()
                embed = await self.get_embed()
                await interaction.response.edit_message(embed=embed, view=self)
        
        jump_btn.callback = jump_callback
        self.add_item(jump_btn)
        
        self.add_item(next_btn)

class NitroShopView(ui.View):
    def __init__(self, ctx, nitro_system):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.nitro_system = nitro_system
        self.message = None
        self.update_components_task = None
    
    async def init(self):
        """Async initialization to fetch dynamic data"""
        await self.update_components()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.stop()
        
    async def update_components(self):
        self.clear_items()
        
        boost_stock = await self.nitro_system.get_stock("boost")
        basic_stock = await self.nitro_system.get_stock("basic")
        boost_price = await self.nitro_system.get_price("boost")
        basic_price = await self.nitro_system.get_price("basic")
        
        user_bal, _ = await self.nitro_system.economy_system.get_balance(self.ctx.author.id)
        
        # Nitro Boost Button
        boost_btn = ui.Button(
            label=f"Buy Nitro Boost ({humanize_number(boost_price)})",
            style=discord.ButtonStyle.blurple,
            emoji="🚀",
            disabled=(boost_stock <= 0 or user_bal < boost_price)
        )
        boost_btn.callback = lambda i: self.buy_callback(i, "boost")
        self.add_item(boost_btn)
        
        # Nitro Basic Button
        basic_btn = ui.Button(
            label=f"Buy Nitro Basic ({humanize_number(basic_price)})",
            style=discord.ButtonStyle.secondary,
            emoji="⭐",
            disabled=(basic_stock <= 0 or user_bal < basic_price)
        )
        basic_btn.callback = lambda i: self.buy_callback(i, "basic")
        self.add_item(basic_btn)
    
    async def buy_callback(self, interaction: discord.Interaction, item_type: str):
        # logging import isn't in this file, but we can assume standard logging setup if we added it,
        # but for now let's just rely on the system logs we added.
        # Actually, adding print for local debugging or using bot logger if available is good practice.
        # But let's stick to modifying logic or minimal logging.
        pretty_name = "Nitro Boost" if item_type == "boost" else "Nitro Basic"
        price = await self.nitro_system.get_price(item_type)
        
        # Confirm Dialog
        confirm_view = ConfirmView(self.ctx.author, disable_buttons=True)

        await interaction.response.send_message(
            f"Are you sure you want to purchase **{pretty_name}** for **{humanize_number(price)}**?",
            view=confirm_view,
            ephemeral=True
        )
        
        await confirm_view.wait()

        if confirm_view.result:
            success, msg = await self.nitro_system.purchase_nitro(self.ctx, item_type)
            
            if success:
                # Update buttons on the main view
                await self.update_components()
                try:
                    await self.message.edit(view=self)
                except: pass
                
                await interaction.followup.send(f"✅ {msg}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
        else:
            await interaction.edit_original_response(content="Purchase cancelled.", view=confirm_view)

    async def get_embed(self):
        boost_stock = await self.nitro_system.get_stock("boost")
        basic_stock = await self.nitro_system.get_stock("basic")
        boost_price = await self.nitro_system.get_price("boost")
        basic_price = await self.nitro_system.get_price("basic")
        
        currency_symbol = await self.ctx.cog.config.currency_symbol()
        
        embed = discord.Embed(
            title="<a:zz_unicorn_dot:965576604212396092> Unicornia Nitro Shop",
            description=f"Exchange your hard-earned {currency_symbol} for Discord Nitro!\n"
                        f"Items are delivered manually by Kirin after purchase.",
            color=discord.Color(0xff73fa)
        )
        
        embed.add_field(
            name="🚀 Nitro Boost (1 Month)",
            value=f"**Price:** {humanize_number(boost_price)} {currency_symbol}\n**Stock:** {boost_stock}",
            inline=True
        )
        
        embed.add_field(
            name="⭐ Nitro Basic (1 Month)",
            value=f"**Price:** {humanize_number(basic_price)} {currency_symbol}\n**Stock:** {basic_stock}",
            inline=True
        )
        
        embed.set_footer(text="Stock is limited! • No refunds once code is sent.")
        
        return embed