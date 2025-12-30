import asyncio
import contextlib
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Union

import discord
from discord import ButtonStyle, Interaction, TextStyle
from discord.ui import Button, Modal, TextInput, View
from discord.ui.item import Item
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import box, humanize_list, pagify

from .functions import Functions
from .utils import (
    can_close,
    close_ticket,
    update_active_overview,
)

log = logging.getLogger("red.vrt.supportview")


async def wait_reply(
    ctx: commands.Context,
    timeout: Optional[int] = 60,
    delete: Optional[bool] = True,
) -> Optional[str]:
    def check(message: discord.Message):
        return message.author == ctx.author and message.channel == ctx.channel

    try:
        reply = await ctx.bot.wait_for("message", timeout=timeout, check=check)
        res = reply.content
        if delete:
            with contextlib.suppress(discord.HTTPException, discord.NotFound, discord.Forbidden):
                await reply.delete(delay=10)
        if res.lower().strip() == "cancel":
            return None
        return res.strip()
    except asyncio.TimeoutError:
        return None


def get_color(color: str) -> ButtonStyle:
    if color == "red":
        style = ButtonStyle.red
    elif color == "blue":
        style = ButtonStyle.blurple
    elif color == "green":
        style = ButtonStyle.green
    else:
        style = ButtonStyle.grey
    return style


def get_modal_style(styletype: str) -> TextStyle:
    if styletype == "short":
        style = TextStyle.short
    elif styletype == "long":
        style = TextStyle.long
    else:
        style = TextStyle.paragraph
    return style


class Confirm(View):
    def __init__(self, ctx):
        self.ctx = ctx
        self.value = None
        super().__init__(timeout=60)

    async def interaction_check(self, interaction: Interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                content="You are not allowed to interact with this button.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes", style=ButtonStyle.green)
    async def confirm(self, interaction: Interaction, button: Button):
        if not await self.interaction_check(interaction):
            return
        self.value = True
        with contextlib.suppress(discord.NotFound):
            await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="No", style=ButtonStyle.red)
    async def cancel(self, interaction: Interaction, button: Button):
        if not await self.interaction_check(interaction):
            return
        self.value = False
        with contextlib.suppress(discord.NotFound):
            await interaction.response.defer()
        self.stop()


async def confirm(ctx, msg: discord.Message):
    try:
        view = Confirm(ctx)
        await msg.edit(view=view)
        await view.wait()
        if view.value is None:
            await msg.delete()
        else:
            await msg.edit(view=None)
        return view.value
    except Exception as e:
        log.warning(f"Confirm Error: {e}")
        return None


class TestButton(View):
    def __init__(
        self,
        style: str = "grey",
        label: str = "Button Test",
        emoji: Union[discord.Emoji, discord.PartialEmoji, str] = None,
    ):
        super().__init__()
        style = get_color(style)
        butt = discord.ui.Button(label=label, style=style, emoji=emoji)
        self.add_item(butt)


class CloseReasonModal(Modal):
    def __init__(self):
        self.reason = None
        super().__init__(title="Closing your ticket", timeout=120)
        self.field = TextInput(
            label="Reason for closing",
            style=TextStyle.short,
            required=True,
        )
        self.add_item(self.field)

    async def on_submit(self, interaction: Interaction):
        self.reason = self.field.value
        with contextlib.suppress(discord.NotFound):
            await interaction.response.defer()
        self.stop()


class CloseView(View):
    def __init__(
        self,
        bot: Red,
        config: Config,
        owner_id: int,
        channel: Union[discord.TextChannel, discord.Thread],
    ):
        super().__init__(timeout=None)
        self.bot = bot
        self.config = config
        self.owner_id = owner_id
        self.channel = channel

        self.closeticket.custom_id = str(channel.id)

    async def on_error(self, interaction: Interaction, error: Exception, item: Item[Any]):
        log.warning(
            f"View failed for user ticket {self.owner_id} in channel {self.channel.name} in {self.channel.guild.name}",
            exc_info=error,
        )
        return await super().on_error(interaction, error, item)

    @discord.ui.button(label="Close", style=ButtonStyle.danger)
    async def closeticket(self, interaction: Interaction, button: Button):
        if not interaction.guild or not interaction.channel:
            return
        user = interaction.guild.get_member(interaction.user.id)
        if not user:
            return

        conf = await self.config.guild(interaction.guild).all()
        txt = "This ticket has already been closed! Please delete it manually."
        if str(self.owner_id) not in conf["opened"]:
            return await interaction.response.send_message(txt, ephemeral=True)
        if str(self.channel.id) not in conf["opened"][str(self.owner_id)]:
            return await interaction.response.send_message(txt, ephemeral=True)

        allowed = await can_close(
            bot=self.bot,
            guild=interaction.guild,
            channel=interaction.channel,
            author=user,
            owner_id=self.owner_id,
            conf=conf,
        )
        if not allowed:
            return await interaction.response.send_message(
                "You do not have permissions to close this ticket",
                ephemeral=True,
            )
            
        requires_reason = conf.get("close_reason", True)
        reason = None
        if requires_reason:
            modal = CloseReasonModal()
            try:
                await interaction.response.send_modal(modal)
            except discord.NotFound as e:
                log.warning("Failed to send ticket modal", exc_info=e)
                txt = "Something went wrong, please try again."
                try:
                    await interaction.followup.send(txt, ephemeral=True)
                except discord.NotFound:
                    await interaction.channel.send(txt, delete_after=10)
                return

            await modal.wait()
            if modal.reason is None:
                return
            reason = modal.reason
            await interaction.followup.send("Closing...", ephemeral=True)
        else:
            await interaction.response.send_message("Closing...", ephemeral=True)
        
        owner = self.channel.guild.get_member(int(self.owner_id))
        if not owner:
            owner = await self.bot.fetch_user(int(self.owner_id))
        await close_ticket(
            bot=self.bot,
            member=owner,
            guild=self.channel.guild,
            channel=self.channel,
            conf=conf,
            reason=reason,
            closedby=interaction.user.name,
            config=self.config,
        )

    @discord.ui.button(label="Remind Instructions", style=ButtonStyle.danger)
    async def remind_instructions(self, interaction: Interaction, button: Button):
        embed = discord.Embed(
            description=(
                "**PLEASE ADHERE TO THE FOLLOWING FORMAT IN ORDER TO BE VERIFIED**\n\n"
                "- Send a selfie while holding your censored ID and your hand written Discord username and also today's date within the same selfie.\n\n"
                "- The photo on the ID and year of birth should be clearly visible (day and month of birth should also be censored unless needed)."
            ),
            color=discord.Color.red()
        )
        embed.set_image(url="https://cdn.discordapp.com/attachments/686096388018405408/1267972588165136496/id-verify.png")
        await interaction.response.send_message(embed=embed)


import io

class SimpleAttachment:
    def __init__(self, url, filename):
        self.url = url
        self.filename = filename

class FileUpload(discord.ui.Item):
    def __init__(self, custom_id: str, required: bool = True, min_values: int = 1, max_values: int = 3):
        super().__init__()
        self.custom_id = custom_id
        self.required = required
        self.min_values = min_values
        self.max_values = max_values
        self._uploaded_attachments = []

    @property
    def type(self) -> discord.ComponentType:
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


class VerificationModal(discord.ui.Modal, title="Verification"):
    def __init__(self, bot: Red, guild: discord.Guild, config: Config, user: discord.Member):
        super().__init__()
        self.bot = bot
        self.guild = guild
        self.config = config
        self.user = user
        
        # 1. Use custom FileUpload component
        self.image = FileUpload(
            custom_id="verification_image",
            required=True,
            min_values=1,
            max_values=3,
        )

        # 2. Wrap it in discord.ui.Label
        self.label = discord.ui.Label(
            text="Upload your verification images",
            description="Please upload up to 3 images for verification.",
            component=self.image
        )
        self.add_item(self.label)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        attachments = []
        if self.image.values:
            attachments = self.image.values
        
        # Fallback: check interaction data directly if custom component retrieval failed
        if not attachments and hasattr(interaction, 'data') and 'resolved' in interaction.data and 'attachments' in interaction.data['resolved']:
            raw_attachments = interaction.data['resolved']['attachments']
            if raw_attachments:
                for attachment_data in raw_attachments.values():
                    attachments.append(SimpleAttachment(
                        url=attachment_data.get('url'),
                        filename=attachment_data.get('filename', 'image.png')
                    ))

        cog = self.bot.get_cog("Tickets")
        if not cog:
            return await interaction.followup.send("Tickets cog not loaded!", ephemeral=True)
            
        result = await cog.create_ticket_for_user(self.user)
        
        # Post image to the new ticket channel
        conf = await self.config.guild(self.guild).all()
        opened = conf["opened"]
        uid = str(self.user.id)
        if uid in opened:
            # Get the most recently opened ticket
            # (Sorting by ID is safer than max() on keys if keys are strings)
            ticket_ids = sorted([int(x) for x in opened[uid].keys()], reverse=True)
            if ticket_ids:
                latest_channel_id = ticket_ids[0]
                channel = self.guild.get_channel(latest_channel_id)
                
                if channel and attachments:
                    for i, attachment in enumerate(attachments):
                        embed = discord.Embed(title=f"Verification Image {i+1}", color=discord.Color.green())
                        embed.set_author(name=self.user.display_name, icon_url=self.user.display_avatar.url)
                        
                        try:
                            embed.set_image(url=attachment.url)
                            await channel.send(embed=embed)
                        except Exception as e:
                            log.error(f"Failed to send verification image to {channel.name}", exc_info=e)
                            await channel.send(f"Failed to load verification image {i+1}: {attachment.url}")

        await interaction.followup.send(result, ephemeral=True)


class SupportButton(Button):
    def __init__(self, conf: dict, mock_user: discord.Member = None):
        super().__init__(
            style=get_color(conf["button_color"]),
            label=conf["button_text"],
            custom_id="create_ticket_button",
            emoji=conf["button_emoji"],
            disabled=False,
        )
        self.conf = conf
        self.mock_user = mock_user

    async def callback(self, interaction: Interaction):
        try:
            await self.create_ticket(interaction)
        except Exception as e:
            guild = interaction.guild.name
            user = self.mock_user.name if self.mock_user else interaction.user.name
            log.exception(f"Failed to create ticket in {guild} for {user}", exc_info=e)

    async def create_ticket(self, interaction: Interaction):
        guild = interaction.guild
        user = self.mock_user or guild.get_member(interaction.user.id)
        if not guild:
            return

        conf = await self.view.config.guild(guild).all()
        
        if conf["suspended_msg"]:
            em = discord.Embed(
                title="Ticket System Suspended",
                description=conf["suspended_msg"],
                color=discord.Color.yellow(),
            )
            return await interaction.response.send_message(embed=em, ephemeral=True)

        for rid_uid in conf["blacklist"]:
            if rid_uid == user.id:
                em = discord.Embed(
                    description="You been blacklisted from creating tickets!",
                    color=discord.Color.red(),
                )
                return await interaction.response.send_message(embed=em, ephemeral=True)
            elif rid_uid in [r.id for r in user.roles]:
                em = discord.Embed(
                    description="You have a role that has been blacklisted from creating tickets!",
                    color=discord.Color.red(),
                )
                return await interaction.response.send_message(embed=em, ephemeral=True)

        if required_roles := conf.get("required_roles", []):
            if not any(r.id in required_roles for r in user.roles):
                roles = [guild.get_role(i).mention for i in required_roles if guild.get_role(i)]
                em = discord.Embed(
                    description="You must have one of the following roles to open this ticket: "
                    + humanize_list(roles),
                    color=discord.Color.red(),
                )
                return await interaction.response.send_message(embed=em, ephemeral=True)

        max_tickets = conf["max_tickets"]
        opened = conf["opened"]
        uid = str(user.id)
        if uid in opened and max_tickets <= len(opened[uid]):
            channels = "\n".join([f"<#{i}>" for i in opened[uid]])
            em = discord.Embed(
                description="You have the maximum amount of tickets opened already!{}".format(f"\n{channels}"),
                color=discord.Color.red(),
            )
            return await interaction.response.send_message(embed=em, ephemeral=True)

        # Open Verification Modal
        modal = VerificationModal(self.view.bot, guild, self.view.config, user)
        await interaction.response.send_modal(modal)


class PanelView(View):
    def __init__(
        self,
        bot: Red,
        guild: discord.Guild,
        config: Config,
        conf: dict,
        mock_user: Optional[discord.Member] = None,
        timeout: Optional[int] = None,
    ):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild = guild
        self.config = config
        self.conf = conf
        self.add_item(SupportButton(conf, mock_user=mock_user))

    async def start(self):
        chan = self.guild.get_channel(self.conf["channel_id"])
        if not isinstance(chan, discord.TextChannel):
            return
        message = await chan.fetch_message(self.conf["message_id"])
        await message.edit(view=self)
