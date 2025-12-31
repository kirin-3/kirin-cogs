import discord
from discord import ButtonStyle, Interaction, TextStyle
from discord.ui import Button, Modal, TextInput, View, Item
from typing import Any, Dict, List, Optional, Union
import logging

from .models import QUESTIONS, ProfileData

log = logging.getLogger("red.profile.views")

class SimpleAttachment:
    def __init__(self, url, filename):
        self.url = url
        self.filename = filename

class FileUpload(Item):
    def __init__(self, custom_id: str, required: bool = True, min_values: int = 1, max_values: int = 1):
        super().__init__()
        self.custom_id = custom_id
        self.required = required
        self.min_values = min_values
        self.max_values = max_values
        self._uploaded_attachments = []

    @property
    def type(self) -> discord.ComponentType:
        # 19 is Attachment
        return discord.ComponentType(19)

    def to_component_dict(self):
        return {
            "type": 19,
            "custom_id": self.custom_id,
            "required": self.required,
            "min_values": self.min_values,
            "max_values": self.max_values,
        }

    def refresh_component(self, component):
        self._uploaded_attachments = component.values

    @property
    def values(self):
        return self._uploaded_attachments

class ProfileModal(Modal):
    def __init__(self, field_id: str, label: str, question: str, max_length: int, required: bool, style: TextStyle, current_value: str = ""):
        super().__init__(title=label)
        self.field_id = field_id
        self.input = TextInput(
            label=question,
            placeholder=f"Enter your {label.lower()} here...",
            default=current_value,
            min_length=1 if required else 0,
            max_length=max_length,
            required=required,
            style=style
        )
        self.add_item(self.input)
        self.value = None

    async def on_submit(self, interaction: Interaction):
        self.value = self.input.value
        await interaction.response.defer()
        self.stop()

class PictureUploadModal(Modal):
    def __init__(self):
        super().__init__(title="Profile Picture")
        self.image = FileUpload(
            custom_id="profile_picture_upload",
            required=True,
            min_values=1,
            max_values=1,
        )
        # Wrap it in a Label (as seen in tickets reference)
        # Note: discord.ui.Label might not exist in all d.py versions, 
        # but the reference used it. Let's try to follow the reference closely.
        # Actually, standard d.py 2.x doesn't have ui.Label for this purpose usually.
        # Looking at tickets/common/views.py:375
        # self.label = discord.ui.Label(...)
        
        # If discord.ui.Label doesn't exist, we might need a different approach.
        # But I'll follow the reference.
        try:
            self.label = discord.ui.Label(
                text="Upload your profile picture",
                description="Please upload an image for your profile.",
                component=self.image
            )
            self.add_item(self.label)
        except AttributeError:
            # Fallback if Label is not available
            self.add_item(self.image)

    async def on_submit(self, interaction: Interaction):
        attachments = []
        if self.image.values:
            attachments = self.image.values
        
        # Fallback check interaction data directly
        if not attachments and hasattr(interaction, 'data') and 'resolved' in interaction.data and 'attachments' in interaction.data['resolved']:
            raw_attachments = interaction.data['resolved']['attachments']
            if raw_attachments:
                for attachment_data in raw_attachments.values():
                    attachments.append(SimpleAttachment(
                        url=attachment_data.get('url'),
                        filename=attachment_data.get('filename', 'image.png')
                    ))
        
        if attachments:
            self.value = attachments[0].url
        else:
            self.value = None
            
        await interaction.response.defer()
        self.stop()

class ProfileBuilderView(View):
    def __init__(self, user: discord.Member, current_data: ProfileData):
        super().__init__(timeout=600)
        self.user = user
        self.data = current_data.copy()
        self.submitted = False
        self._setup_buttons()

    def _setup_buttons(self):
        self.clear_items()
        for q in QUESTIONS:
            field_id = q["id"]
            label = q["label"]
            is_required = q.get("required", False)
            has_value = field_id in self.data and self.data[field_id]
            
            style = ButtonStyle.green if has_value else (ButtonStyle.blurple if is_required else ButtonStyle.grey)
            status = "✅" if has_value else ("*" if is_required else "")
            
            btn = Button(label=f"{status}{label}", style=style, custom_id=f"btn_{field_id}")
            btn.callback = self._make_callback(q)
            self.add_item(btn)

        # Add Submit and Cancel buttons
        submit_btn = Button(label="Submit Profile", style=ButtonStyle.success, row=4)
        submit_btn.callback = self.submit_callback
        self.add_item(submit_btn)

        cancel_btn = Button(label="Cancel", style=ButtonStyle.danger, row=4)
        cancel_btn.callback = self.cancel_callback
        self.add_item(cancel_btn)

    def _make_callback(self, question_data):
        async def callback(interaction: Interaction):
            if interaction.user.id != self.user.id:
                return await interaction.response.send_message("This menu is not for you.", ephemeral=True)
            
            field_id = question_data["id"]
            if question_data.get("type") == "image":
                modal = PictureUploadModal()
                await interaction.response.send_modal(modal)
                await modal.wait()
                if modal.value:
                    self.data[field_id] = modal.value
            else:
                style = TextStyle.long if question_data.get("style") == "long" else TextStyle.short
                modal = ProfileModal(
                    field_id=field_id,
                    label=question_data["label"],
                    question=question_data["question"],
                    max_length=question_data.get("max_length", 100),
                    required=question_data.get("required", False),
                    style=style,
                    current_value=str(self.data.get(field_id, ""))
                )
                await interaction.response.send_modal(modal)
                await modal.wait()
                if modal.value is not None:
                    val = modal.value
                    if question_data.get("type") == "int":
                        try:
                            val = int(val)
                        except ValueError:
                            return await interaction.followup.send("Age must be a number!", ephemeral=True)
                    self.data[field_id] = val

            self._setup_buttons()
            await interaction.edit_original_response(view=self)
            
        return callback

    async def submit_callback(self, interaction: Interaction):
        # Validate required fields
        missing = []
        for q in QUESTIONS:
            if q.get("required") and (q["id"] not in self.data or not self.data[q["id"]]):
                missing.append(q["label"])
        
        if missing:
            return await interaction.response.send_message(f"Please fill in the following required fields: {', '.join(missing)}", ephemeral=True)
        
        self.submitted = True
        self.stop()
        await interaction.response.defer()

    async def cancel_callback(self, interaction: Interaction):
        self.stop()
        await interaction.response.send_message("Profile creation cancelled.", ephemeral=True)

class ProfileDeleteConfirmView(View):
    def __init__(self, user: discord.Member):
        super().__init__(timeout=60)
        self.user = user
        self.value = False

    @discord.ui.button(label="Yes, Delete", style=ButtonStyle.danger)
    async def confirm(self, interaction: Interaction, button: Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("This is not for you.", ephemeral=True)
        self.value = True
        self.stop()
        await interaction.response.defer()

    @discord.ui.button(label="No, Cancel", style=ButtonStyle.grey)
    async def cancel(self, interaction: Interaction, button: Button):
        if interaction.user.id != self.user.id:
            return await interaction.response.send_message("This is not for you.", ephemeral=True)
        self.value = False
        self.stop()
        await interaction.response.defer()

class ProfileStickyView(View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Create/Edit Profile", style=ButtonStyle.green, custom_id="profile_create_edit")
    async def create_edit(self, interaction: Interaction, button: Button):
        await self.cog.handle_create_edit(interaction)

    @discord.ui.button(label="Delete Profile", style=ButtonStyle.red, custom_id="profile_delete")
    async def delete(self, interaction: Interaction, button: Button):
        await self.cog.handle_delete_request(interaction)
