from redbot.core import commands
import discord

class rulesaccept(commands.Cog):
    """Cog for rule acceptance with button and modal."""

    def __init__(self):
        super().__init__()

    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def sendrules(self, ctx):
        """Send the rules acceptance button."""
        view = rulesacceptView()
        await ctx.send(
            "Please read the rules. When ready, click the button below to accept.",
            view=view
        )

class rulesacceptView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(rulesacceptButton())

class rulesacceptButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="I have read and accept the rules.",
            style=discord.ButtonStyle.success,
            custom_id="rulesaccept_button"
        )

    async def callback(self, interaction: discord.Interaction):
        modal = rulesacceptModal()
        await interaction.response.send_modal(modal)

class rulesacceptModal(discord.ui.Modal, title="Rules Acceptance"):
    answer = discord.ui.TextInput(
        label="Type exactly: I agree to the rules.",
        placeholder="I agree to the rules.",
        required=True,
        max_length=30
    )

    async def on_submit(self, interaction: discord.Interaction):
        valid_responses = ["I agree to the rules.", "I Agree To The Rules."]
        if self.answer.value.strip() in valid_responses:
            guild = interaction.guild
            member = interaction.user
            role_id = 686098839651876908
            role = guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Accepted the rules.")
                    await interaction.response.send_message(
                        "Thank you! You have accepted the rules and have been given access.", ephemeral=True
                    )
                    # Send the additional info as a followup ephemeral message
                    await interaction.followup.send(
                        "You will need a role from <#708066544688562196> channel as well for full access.",
                        ephemeral=True
                    )
                except Exception as e:
                    await interaction.response.send_message(
                        f"Could not assign the role: {e}", ephemeral=True
                    )
            else:
                await interaction.response.send_message(
                    "Role not found. Please contact an admin.", ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "You must type exactly: I agree to the rules.", ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(rulesaccept())
