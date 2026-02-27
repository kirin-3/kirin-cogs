import discord
from discord import ui
from redbot.core.utils.chat_formatting import humanize_number

class ContestDashboardView(ui.LayoutView):
    """V2 Components Dashboard for the Cutie of the Month Contest."""
    
    def __init__(self, cog, contest_number: int, texts: dict):
        super().__init__(timeout=None) # Persistent view
        self.cog = cog
        self.contest_number = contest_number
        self.texts = texts # Dictionary holding the formatted description, terms, prizes, votes text
        
        # Determine current state: "home", "terms", "prizes", "votes"
        self.current_tab = "home"
        self.update_components()

    def update_components(self):
        self.clear_items()
        
        # Main Container
        container = ui.Container(accent_color=discord.Color.from_rgb(175, 126, 235))
        
        # Display the active tab's content
        if self.current_tab == "home":
             content = f"## 🎀 Cutie of the Month {self.contest_number}\n{self.texts['description']}"
        elif self.current_tab == "terms":
             content = f"### 📜 Entry Terms\n{self.texts['terms']}"
        elif self.current_tab == "prizes":
             content = f"### 🏆 Prizes\n{self.texts['prizes']}"
        elif self.current_tab == "votes":
             content = f"### 🗳️ How to Vote\n{self.texts['votes']}"
             
        container.add_item(ui.TextDisplay(content=content))
        container.add_item(ui.Separator())
        
        # Navigation Buttons
        home_btn = ui.Button(label="Home", style=discord.ButtonStyle.primary if self.current_tab == "home" else discord.ButtonStyle.secondary, custom_id="cotm:home", row=0)
        terms_btn = ui.Button(label="Terms", style=discord.ButtonStyle.primary if self.current_tab == "terms" else discord.ButtonStyle.secondary, custom_id="cotm:terms", row=0)
        prizes_btn = ui.Button(label="Prizes", style=discord.ButtonStyle.primary if self.current_tab == "prizes" else discord.ButtonStyle.secondary, custom_id="cotm:prizes", row=0)
        votes_btn = ui.Button(label="How to Vote", style=discord.ButtonStyle.primary if self.current_tab == "votes" else discord.ButtonStyle.secondary, custom_id="cotm:votes", row=0)
        
        # Special action button
        standings_btn = ui.Button(label="Check Standings", style=discord.ButtonStyle.success, custom_id="cotm:standings", row=1)
        
        home_btn.callback = self.home_button
        terms_btn.callback = self.terms_button
        prizes_btn.callback = self.prizes_button
        votes_btn.callback = self.votes_button
        standings_btn.callback = self.standings_button
        
        self.add_item(container)
        self.add_item(ui.ActionRow(home_btn, terms_btn, prizes_btn, votes_btn))
        self.add_item(ui.ActionRow(standings_btn))

    async def home_button(self, interaction: discord.Interaction):
        self.current_tab = "home"
        self.update_components()
        await interaction.response.edit_message(view=self)
        
    async def terms_button(self, interaction: discord.Interaction):
        self.current_tab = "terms"
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def prizes_button(self, interaction: discord.Interaction):
        self.current_tab = "prizes"
        self.update_components()
        await interaction.response.edit_message(view=self)

    async def votes_button(self, interaction: discord.Interaction):
        self.current_tab = "votes"
        self.update_components()
        await interaction.response.edit_message(view=self)
        
    async def standings_button(self, interaction: discord.Interaction):
        # Ephemeral check standings logic
        await interaction.response.defer(ephemeral=True)
        
        # Find the entries channel
        import cotm.const as const
        entries_channel = interaction.guild.get_channel(const.ENTRIES_CHANNEL_ID)
             
        if not entries_channel:
             await interaction.followup.send("❌ Error: Could not find the entries channel to tally votes.", ephemeral=True)
             return
             
        # Tally the votes
        await interaction.followup.send("Tallying votes, please wait...", ephemeral=True)
        entries = await self.cog._get_contest_results(entries_channel)
        
        # Format the leaderboard via Container
        container = self.cog._build_standings_container(entries, title="📊 Current Standings")
        
        # Edit the followup to show the actual container instead of the "please wait" text
        # Since edit doesn't take 'view' alone if we want to replace text with a Component V2 layout directly,
        # we can just send a new followup or edit the existing one. For V2, passing `view=LayoutView()` flags the message.
        
        class StandingsView(ui.LayoutView):
             def __init__(self, container):
                  super().__init__(timeout=180)
                  self.add_item(container)
                  
        await interaction.edit_original_response(content=None, view=StandingsView(container))
