import discord
from discord import ButtonStyle, Interaction, TextStyle
from discord.ui import Button, Modal, TextInput, View

class ConfessionModal(Modal):
    def __init__(self, cog):
        super().__init__(title="Submit a Confession")
        self.cog = cog
        
        self.confession_input = TextInput(
            label="Your Confession",
            placeholder="Type your confession here...",
            style=TextStyle.long,
            min_length=5,
            max_length=2000,
            required=True
        )
        self.add_item(self.confession_input)

    async def on_submit(self, interaction: Interaction):
        await self.cog.process_confession(interaction, self.confession_input.value)

class StickyView(View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Confess", style=ButtonStyle.primary, custom_id="confess_sticky_button", emoji="🙊")
    async def confess_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(ConfessionModal(self.cog))
