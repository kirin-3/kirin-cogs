from redbot.core import commands, Config
import discord

class rulesaccept(commands.Cog):
    """Cog for rule acceptance with button and modal."""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=862735937)
        default_guild = {
            "rules_channel_id": 684360255798509582,
            "member_role_id": 686098839651876908
        }
        self.config.register_guild(**default_guild)
        self.bot.loop.create_task(self.initialize())
    
    async def initialize(self):
        await self.bot.wait_until_ready()
        self.bot.add_view(rulesacceptView(self))

    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def sendrules(self, ctx):
        """Send the rules acceptance button."""
        view = rulesacceptView(self)
        await ctx.send(
            "Please read the rules. When ready, click the button below to accept.",
            view=view
        )
    
    @commands.command()
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def setrole(self, ctx, role: discord.Role):
        """Set the role to be assigned when rules are accepted."""
        await self.config.guild(ctx.guild).member_role_id.set(role.id)
        await ctx.send(f"Role set to {role.name}.")

class rulesacceptView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(rulesacceptButton(cog))

class rulesacceptButton(discord.ui.Button):
    def __init__(self, cog):
        super().__init__(
            label="I have read and accept the rules.",
            style=discord.ButtonStyle.success,
            custom_id="rulesaccept_button"
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        modal = rulesacceptModal(self.cog)
        await interaction.response.send_modal(modal)

class rulesacceptModal(discord.ui.Modal, title="Rules Acceptance"):
    def __init__(self, cog):
        super().__init__()
        self.cog = cog
        
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
            role_id = await self.cog.config.guild(guild).member_role_id()
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
    await bot.add_cog(rulesaccept(bot))
