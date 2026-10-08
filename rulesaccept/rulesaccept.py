import logging
from datetime import UTC, datetime

import discord
from redbot.core import Config, commands

log = logging.getLogger("red.kirin_cogs.rulesaccept")

MUTED_ROLE_ID = 686252873583165520  # same role the moderation cog mutes with
ROLES_CHANNEL_ID = 708066544688562196  # primary-roles
PRIMARY_ROLE_IDS = (  # offered in the modal, in this order
    686097165046513720,  # Trans Femme
    885983046371786784,  # Trans Masc
    686097206188703769,  # Femboy
    686096929754710037,  # Sissy
    764536286533910539,  # Bi-Gender
    764536297980297226,  # Gender Fluid
    885994327132749845,  # Genderqueer
    764536300824821760,  # Non-Binary
    764536294985826305,  # Female
    764536291944562729,  # Male
    764537583274557450,  # Other
)


def _agrees(text: str) -> bool:
    """Whether the text is the acceptance phrase, ignoring case, spacing, quotes and closing punctuation."""
    return " ".join(text.casefold().split()).strip("\"'`*\u201c\u201d\u2018\u2019.! ") == "i agree to the rules"


class RulesAccept(commands.Cog):
    """Cog for rule acceptance with button and modal."""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=862735937)
        default_guild = {"member_role_id": 686098839651876908}
        self.config.register_guild(**default_guild)

    def _preflight_role_edit(self, guild, role):
        if not guild.me.guild_permissions.manage_roles:
            return "I do not have the Manage Roles permission."
        if role.managed is True or role.is_default() is True:
            return "This role cannot be assigned because it is a managed or default role."
        if role >= guild.me.top_role:
            return "I can't assign that role (it's higher than or equal to my top role)."
        return None

    def _setter_error(self, author: discord.Member, role: discord.Role) -> str | None:
        """The button grants this role to anyone, so only let people pick roles they could grant themselves."""
        if author.id == author.guild.owner_id:
            return None
        if not author.guild_permissions.manage_roles:
            return "You need the Manage Roles permission to choose this role."
        if role >= author.top_role:
            return "You can't choose a role that is higher than or equal to your top role."
        return None

    async def cog_load(self):
        self.bot.add_view(rulesacceptView(self))

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def sendrules(self, ctx):
        """Send the rules acceptance button."""
        view = rulesacceptView(self)
        await ctx.send("Please read the rules. When ready, click the button below to accept.", view=view)

    @commands.command()  # pyright: ignore[reportArgumentType]
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def setrole(self, ctx, role: discord.Role):
        """Set the role to be assigned when rules are accepted."""
        error_msg = self._setter_error(ctx.author, role) or self._preflight_role_edit(ctx.guild, role)
        if error_msg:
            await ctx.send(error_msg)
            return
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
            label="I have read and accept the rules.", style=discord.ButtonStyle.success, custom_id="rulesaccept_button"
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction):
        modal = rulesacceptModal(self.cog, interaction.guild)
        await interaction.response.send_modal(modal)


class rulesacceptModal(discord.ui.Modal, title="Rules Acceptance"):
    def __init__(self, cog, guild: discord.Guild | None = None):
        super().__init__()
        self.cog = cog
        self.answer = discord.ui.TextInput(placeholder="I agree to the rules", required=True, max_length=30)
        self.add_item(discord.ui.Label(text="Type: I agree to the rules", component=self.answer))
        # Without a guild, or where none of the roles exist, the modal is the phrase alone
        roles = [role for role_id in PRIMARY_ROLE_IDS if guild and (role := guild.get_role(role_id))]
        self.role_select: discord.ui.Select | None = None
        if roles:
            self.role_select = discord.ui.Select(
                placeholder="Choose a role",
                options=[discord.SelectOption(label=role.name, value=str(role.id)) for role in roles],
            )
            self.add_item(
                discord.ui.Label(
                    text="Pick your primary role",
                    description="You can change it or add more roles later.",
                    component=self.role_select,
                )
            )

    def _primary_role(self, guild: discord.Guild) -> discord.Role | None:
        """The primary role picked in the modal. The value comes from the client, so only listed roles count."""
        if self.role_select is None or not self.role_select.values:
            return None
        picked = self.role_select.values[0]
        return guild.get_role(int(picked)) if picked in {str(role_id) for role_id in PRIMARY_ROLE_IDS} else None

    async def _log_acceptance(self, interaction: discord.Interaction):
        log_channel_id = 1422656113077256322  # Your specified logging channel ID
        log_channel = self.cog.bot.get_channel(log_channel_id)

        if log_channel:
            member = interaction.user
            typed_text = self.answer.value

            # Create a rich embed for logging
            embed = discord.Embed(title="Rule Acceptance Log", color=discord.Color.blue(), timestamp=datetime.now(UTC))
            embed.add_field(name="Member", value=f"{member.mention} (`{member.id}`)", inline=False)
            embed.add_field(name="What they typed", value=f"```{typed_text}```", inline=False)

            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                log.warning(f"I don't have permissions to send messages in the log channel: {log_channel_id}")
            except discord.HTTPException:
                log.exception("Failed to send the rule-acceptance log message")
        else:
            log.warning(f"Could not find the log channel with ID: {log_channel_id}")

    async def on_submit(self, interaction: discord.Interaction):
        # Reply first: Discord allows 3 seconds, and a slow log send must not use them up
        try:
            await self._respond(interaction)
        finally:
            await self._log_acceptance(interaction)

    async def _respond(self, interaction: discord.Interaction):
        if _agrees(self.answer.value):
            guild = interaction.guild
            member = interaction.user
            if guild is None or not isinstance(member, discord.Member):
                await interaction.response.send_message(
                    "This action can only be performed in a server.", ephemeral=True
                )
                return
            if member.get_role(MUTED_ROLE_ID) is not None:  # accepting again must not undo a mute
                await interaction.response.send_message(
                    "You can't accept the rules while you're muted.", ephemeral=True
                )
                return
            role_id = await self.cog.config.guild(guild).member_role_id()
            role = guild.get_role(role_id)
            if role:
                primary = self._primary_role(guild)
                roles = [role, primary] if primary else [role]
                error_msg = next(filter(None, (self.cog._preflight_role_edit(guild, r) for r in roles)), None)
                if error_msg:
                    await interaction.response.send_message(error_msg, ephemeral=True)
                    return
                # Granting roles can outlast the 3 seconds Discord gives to reply, which expires the interaction
                await interaction.response.defer(ephemeral=True)
                try:
                    await member.add_roles(*roles, reason="Accepted the rules.")
                except discord.Forbidden:
                    message = "I do not have permission to assign this role."
                except discord.HTTPException:
                    log.exception("Failed to grant the rules-acceptance role")
                    message = "Discord could not assign the role. Please try again or contact an administrator."
                except Exception:
                    log.exception("Unexpected failure while granting the rules-acceptance role")
                    message = "The role could not be assigned. Please contact an administrator."
                else:
                    if primary:
                        message = (
                            "Thank you! You have accepted the rules and now have access to the server. "
                            f"You can change your role or add more in <#{ROLES_CHANNEL_ID}>."
                        )
                    else:
                        message = (
                            "Thank you! You have accepted the rules. "
                            f"Pick a role in <#{ROLES_CHANNEL_ID}> for full access."
                        )
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message("Role not found. Please contact an admin.", ephemeral=True)
        else:
            await interaction.response.send_message("Please type: I agree to the rules", ephemeral=True)


async def setup(bot):
    await bot.add_cog(RulesAccept(bot))
