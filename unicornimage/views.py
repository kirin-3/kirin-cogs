import discord
from discord import ui
from typing import List, Dict, Any
import aiohttp
import io

class LoraListView(ui.LayoutView):
    """
    V2 Component View for listing LoRAs with pagination and image attachments.
    """
    def __init__(self, loras: Dict[str, Any], session: aiohttp.ClientSession):
        super().__init__(timeout=180)
        self.loras = loras
        self.lora_list = list(loras.items())
        self.session = session
        self.current_page = 0
        self.items_per_page = 2
        # Initial components will be set by send_initial

    async def fetch_images(self, page_items):
        files = []
        filenames_map = {} # key -> filename
        
        for key, data in page_items:
            url = data.get("image_url")
            if url:
                try:
                    async with self.session.get(url) as resp:
                        if resp.status == 200:
                            data_bytes = await resp.read()
                            # Determine extension from url or default to png
                            ext = "png"
                            if "jpeg" in url.lower() or "jpg" in url.lower(): ext = "jpg"
                            elif "webp" in url.lower(): ext = "webp"
                            elif "gif" in url.lower(): ext = "gif"
                            
                            # Clean key for filename
                            clean_key = "".join(c for c in key if c.isalnum() or c in (' ', '_', '-')).strip()
                            filename = f"{clean_key}_{self.current_page}.{ext}"
                            
                            files.append(discord.File(io.BytesIO(data_bytes), filename=filename))
                            filenames_map[key] = filename
                except Exception as e:
                    # Log error or ignore
                    print(f"Failed to load image for {key}: {e}")
                    pass
        return files, filenames_map

    def build_layout(self, page_items, filenames_map, total_pages):
        self.clear_items()
        
        # Main Container
        container = ui.Container(accent_color=discord.Color.blue())
        
        # Header
        container.add_item(ui.TextDisplay(content=f"## 🎨 Available Styles (Page {self.current_page + 1}/{total_pages})\nUse these styles with `/gen` command."))
        container.add_item(ui.Separator())
        
        if not page_items:
             container.add_item(ui.TextDisplay(content="No styles available."))
        
        for key, data in page_items:
            name = data.get("name", key)
            desc = data.get("description", "No description")
            base = data.get("base", "Unknown")
            strength = data.get("strength", "Default")
            triggers = ", ".join(data.get("trigger_words", [])) or "None"
            
            # Format Info
            info = f"### {name} (`{key}`)\n"
            info += f"**Base Model:** {base}\n"
            info += f"**Description:** {desc}\n"
            
            container.add_item(ui.TextDisplay(content=info))
            
            filename = filenames_map.get(key)
            if filename:
                 gallery = ui.MediaGallery()
                 gallery.add_item(media=f"attachment://{filename}")
                 container.add_item(gallery)
                 
            container.add_item(ui.Separator())
            
        # Pagination Buttons
        if total_pages > 1:
            prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
            next_btn = ui.Button(label="▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= total_pages - 1))
            
            prev_btn.callback = self.prev_page
            next_btn.callback = self.next_page
            
            container.add_item(ui.ActionRow(prev_btn, next_btn))
            
        self.add_item(container)

    async def send_initial(self, ctx):
        total_pages = max(1, (len(self.lora_list) - 1) // self.items_per_page + 1)
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.lora_list[start:end]
        
        files, filenames_map = await self.fetch_images(page_items)
        self.build_layout(page_items, filenames_map, total_pages)
        
        await ctx.send(view=self, files=files)

    async def update_page(self, interaction: discord.Interaction):
        # Defer update
        await interaction.response.defer()
        
        total_pages = max(1, (len(self.lora_list) - 1) // self.items_per_page + 1)
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.lora_list[start:end]
        
        files, filenames_map = await self.fetch_images(page_items)
        self.build_layout(page_items, filenames_map, total_pages)
        
        # Use edit_original_response because we deferred
        await interaction.edit_original_response(view=self, attachments=files)

    async def prev_page(self, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_page(interaction)
        else:
             await interaction.response.defer()

    async def next_page(self, interaction: discord.Interaction):
        total_pages = (len(self.lora_list) - 1) // self.items_per_page + 1
        if self.current_page < total_pages - 1:
            self.current_page += 1
            await self.update_page(interaction)
        else:
             await interaction.response.defer()
