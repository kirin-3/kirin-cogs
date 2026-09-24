import asyncio
import io
import logging
import os
from typing import Any

import aiohttp
import discord
from discord import ui

log = logging.getLogger("red.kirin-cogs.unicornimage.views")
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class LoraListView(ui.LayoutView):
    """
    V2 Component View for listing LoRAs with pagination and image attachments.
    """

    def __init__(self, loras: dict[str, Any], session: aiohttp.ClientSession):
        super().__init__(timeout=180)
        self.loras = loras
        self.lora_list = list(loras.items())
        self.session = session
        self.current_page = 0
        self.items_per_page = 2
        # Initial components will be set by send_initial

    async def fetch_images(self, page_items):
        files = []
        filenames_map = {}  # key -> filename

        # Path to 'lorapreviews' inside the cog folder
        base_path = os.path.join(os.path.dirname(__file__), "lorapreviews")

        for key, data in page_items:
            image_found = False

            # 1. Try Local Files
            if os.path.exists(base_path):
                # Check for common extensions
                for ext in [".png", ".jpg", ".jpeg", ".webp"]:
                    local_filename = f"{key}{ext}"
                    file_path = os.path.join(base_path, local_filename)

                    if os.path.exists(file_path):
                        try:

                            def _read_file_bytes(path):
                                with open(path, "rb") as f:
                                    return f.read()

                            data_bytes = await asyncio.to_thread(_read_file_bytes, file_path)

                            # Create attachment filename (cleaned)
                            clean_key = "".join(c for c in key if c.isalnum() or c in (" ", "_", "-")).strip()
                            attach_filename = f"{clean_key}_{self.current_page}{ext}"

                            files.append(discord.File(io.BytesIO(data_bytes), filename=attach_filename))
                            filenames_map[key] = attach_filename
                            image_found = True
                            break
                        except Exception:
                            log.exception("Failed to load local LoRA preview %s", local_filename)

            if image_found:
                continue

            # 2. Fallback to URL
            url = data.get("image_url")
            if url:
                try:
                    timeout = aiohttp.ClientTimeout(total=20)
                    async with self.session.get(
                        url,
                        headers={"User-Agent": "UnicornImage/1.0"},
                        timeout=timeout,
                    ) as resp:
                        if resp.status == 200:
                            content_type = resp.headers.get("Content-Type", "").lower()
                            if not content_type.startswith("image/"):
                                log.warning("Rejected non-image LoRA preview for %s: %s", key, content_type)
                                continue
                            chunks: list[bytes] = []
                            downloaded = 0
                            async for chunk in resp.content.iter_chunked(64 * 1024):
                                downloaded += len(chunk)
                                if downloaded > MAX_IMAGE_BYTES:
                                    raise ValueError("LoRA preview exceeds the 10 MiB limit")
                                chunks.append(chunk)
                            data_bytes = b"".join(chunks)
                            # Determine extension
                            ext = "png"
                            if "jpeg" in url.lower() or "jpg" in url.lower():
                                ext = "jpg"
                            elif "webp" in url.lower():
                                ext = "webp"

                            clean_key = "".join(c for c in key if c.isalnum() or c in (" ", "_", "-")).strip()
                            filename = f"{clean_key}_{self.current_page}.{ext}"

                            files.append(discord.File(io.BytesIO(data_bytes), filename=filename))
                            filenames_map[key] = filename
                except Exception:
                    log.exception("Failed to load remote LoRA preview for %s", key)
        return files, filenames_map

    def build_layout(self, page_items, filenames_map, total_pages):
        self.clear_items()

        # Main Container
        container = ui.Container(accent_color=discord.Color.blue())

        # Header
        container.add_item(
            ui.TextDisplay(
                content=f"## 🎨 Available Styles (Page {self.current_page + 1}/{total_pages})\nUse these styles with `/gen` command."
            )
        )
        container.add_item(ui.Separator())

        if not page_items:
            container.add_item(ui.TextDisplay(content="No styles available."))

        for key, data in page_items:
            name = data.get("name", key)
            desc = data.get("description", "No description")
            base = data.get("base", "Unknown")

            # Format Info
            info = f"### {name} (`{key}`)\n"
            info += f"**Base Model:** {base}\n"
            info += f"**Description:** {desc}\n"

            container.add_item(ui.TextDisplay(content=info))

            filename = filenames_map.get(key)
            if filename:
                try:
                    gallery = ui.MediaGallery()
                    gallery.add_item(media=f"attachment://{filename}")
                    container.add_item(gallery)
                except Exception:
                    pass

            container.add_item(ui.Separator())

        # Pagination Buttons
        if total_pages > 1:
            prev_btn = ui.Button(label="◀️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
            next_btn = ui.Button(
                label="▶️", style=discord.ButtonStyle.secondary, disabled=(self.current_page >= total_pages - 1)
            )

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
        await interaction.response.defer()

        total_pages = max(1, (len(self.lora_list) - 1) // self.items_per_page + 1)
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.lora_list[start:end]

        files, filenames_map = await self.fetch_images(page_items)
        self.build_layout(page_items, filenames_map, total_pages)

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
