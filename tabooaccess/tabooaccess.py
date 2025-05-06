from redbot.core import commands
import discord

class TabooAccess(commands.Cog):
    """Cog for managing taboo content access."""

    def __init__(self):
        super().__init__()

    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def sendtaboo(self, ctx):
        """Send the taboo access control buttons."""
        view = TabooAccessView()
        await ctx.send(
            "Click the button below when you understand the rules and ready.",
            view=view
        )

class TabooAccessView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(LetMeInButton())
        self.add_item(LetMeOutButton())

class LetMeInButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Let me in!",
            style=discord.ButtonStyle.success,
            custom_id="tabooaccess_let_me_in"
        )

    async def callback(self, interaction: discord.Interaction):
        modal = TabooAccessModal()
        await interaction.response.send_modal(modal)

class LetMeOutButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Let me out!",
            style=discord.ButtonStyle.danger,
            custom_id="tabooaccess_let_me_out"
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        role_id = 1319776542099767316
        role = guild.get_role(role_id)
        
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason="Removed taboo access.")
                await interaction.response.send_message(
                    "You have been removed from taboo content access.", ephemeral=True
                )
            except Exception as e:
                await interaction.response.send_message(
                    f"Could not remove the role: {e}", ephemeral=True
                )
        else:
            await interaction.response.send_message(
                "You don't have the taboo access role.", ephemeral=True
            )

class TabooAccessModal(discord.ui.Modal, title="Taboo Access Confirmation"):
    def __init__(self):
        super().__init__()
        self.answer = discord.ui.TextInput(
            label="Type 'yes' or 'i agree' to confirm",
            placeholder="yes",
            required=True,
            max_length=10
        )
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction):
        if self.answer.value.strip().lower() in ["yes", "i agree"]:
            guild = interaction.guild
            member = interaction.user
            role_id = 1319776542099767316
            role = guild.get_role(role_id)
            
            if role:
                try:
                    await member.add_roles(role, reason="Accepted taboo access.")
                    await interaction.response.send_message(
                        "Thank you! You have been granted taboo content access.", ephemeral=True
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
                "You must type 'yes' or 'i agree' to confirm.", ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(TabooAccess())
