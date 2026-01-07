import discord
from discord import ui
from typing import List, Dict, Any

class LoraListView(ui.LayoutView):
    """
    V2 Component View for listing LoRAs with pagination.
    """
    def __init__(self, loras: Dict[str, Any]):
        super().__init__(timeout=180)
        self.loras = loras
        # Convert dict to list of (key, data) tuples for pagination
        self.lora_list = list(loras.items())
        self.current_page = 0
        self.items_per_page = 2
        self.update_components()

    def update_components(self):
        self.clear_items()
        
        # Pagination calculations
        total_pages = max(1, (len(self.lora_list) - 1) // self.items_per_page + 1)
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.lora_list[start:end]
        
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
            image_url = data.get("image_url")
            
            # Format Info
            info = f"### {name} (`{key}`)\n"
            info += f"**Base Model:** {base} | **Strength:** {strength}\n"
            info += f"**Description:** {desc}\n"
            info += f"**Triggers:** `{triggers}`\n"
            
            container.add_item(ui.TextDisplay(content=info))
            
            if image_url:
                try:
                    gallery = ui.MediaGallery()
                    gallery.add_item(media=image_url)
                    container.add_item(gallery)
                except Exception:
                    pass

            container.add_item(ui.Separator())
            
        # Pagination Buttons
        if total_pages > 1:
            prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
            next_btn = ui.Button(label="▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= total_pages - 1))
            
            prev_btn.callback = self.prev_page
            next_btn.callback = self.next_page
            
            container.add_item(ui.ActionRow(prev_btn, next_btn))
            
        self.add_item(container)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page = max(0, self.current_page - 1)
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def next_page(self, interaction: discord.Interaction):
        total_pages = (len(self.lora_list) - 1) // self.items_per_page + 1
        self.current_page = min(total_pages - 1, self.current_page + 1)
        self.update_components()
        await interaction.response.edit_message(view=self)
