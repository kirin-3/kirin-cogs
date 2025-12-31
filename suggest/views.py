import discord
from discord import ButtonStyle, Interaction, TextStyle
from discord.ui import Button, Modal, TextInput, View

class SuggestionModal(Modal):
    def __init__(self, cog):
        super().__init__(title="Submit a Suggestion")
        self.cog = cog
        
        self.suggestion_input = TextInput(
            label="Your Suggestion",
            placeholder="Type your suggestion here...",
            style=TextStyle.long,
            min_length=5,
            max_length=2000,
            required=True
        )
        self.add_item(self.suggestion_input)

    async def on_submit(self, interaction: Interaction):
        await self.cog.process_new_suggestion(interaction, self.suggestion_input.value)

class StickyView(View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Make a Suggestion", style=ButtonStyle.success, custom_id="suggest_sticky_button", emoji="💡")
    async def suggest_button(self, interaction: Interaction, button: Button):
        await interaction.response.send_modal(SuggestionModal(self.cog))
