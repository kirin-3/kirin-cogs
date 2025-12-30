import asyncio
import logging
import re
from typing import Optional, Union

import discord
from discord import Embed
from redbot.core import commands
from redbot.core.utils.chat_formatting import box

from ..abc import MixinMeta
from ..common.constants import MODAL_SCHEMA
from ..common.menu import SMALL_CONTROLS, MenuButton, menu
from ..common.utils import prune_invalid_tickets, update_active_overview
from ..common.views import PanelView, TestButton, confirm, wait_reply

log = logging.getLogger("red.vrt.admincommands")


class AdminCommands(MixinMeta):
    @commands.group(aliases=["tset"])
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def tickets(self, ctx: commands.Context):
        """Base support ticket settings"""
        pass

    @tickets.command()
    async def setuphelp(self, ctx: commands.Context):
        """Ticket Setup Guide"""
        em = Embed(
            title="Ticket Setup Guide",
            description=f"To setup the ticket system, follow the steps below.",
            color=ctx.author.color,
        )
        step1 = "Set the category ID that new tickets will be created under if using channel tickets.\n"
        step1 += f"`{ctx.clean_prefix}tickets category <category_id>`"
        em.add_field(name="Step 1", value=step1, inline=False)

        step2 = "Set the channel that the bots ticket panel will be located in.\n"
        step2 += f"`{ctx.clean_prefix}tickets channel <channel_id>`"
        em.add_field(name="Step 2", value=step2, inline=False)

        step3 = "Set the ID of the bots ticket panel message.\n"
        step3 += f"`{ctx.clean_prefix}tickets panelmessage <message_id>`\n"
        step3 += (
            "At this point the ticket panel will be activated, "
            "all following steps are for extra customization.\n"
            f"If you need a message to add the buttons to, you can use the `{ctx.clean_prefix}tickets embed` command.\n"
        )
        step3 += "If the bot is having trouble finding the message, run the command in the same channel as it."
        em.add_field(name="Step 3", value=step3, inline=False)

        step4 = "Set the text of the ticket panel button.\n"
        step4 += f"`{ctx.clean_prefix}tickets buttontext <button_text>`"
        em.add_field(name="Button Text", value=step4, inline=False)

        step5 = "Set the ticket panel button color.\n"
        step5 += "Valid colors are `red`, `blue`, `green`, and `grey`.\n"
        step5 += f"`{ctx.clean_prefix}tickets buttoncolor <button_color>`"
        em.add_field(name="Button Color", value=step5, inline=False)

        step6 = "Set the button emoji for the ticket panel.\n"
        step6 += f"`{ctx.clean_prefix}tickets buttonemoji <emoji>`"
        em.add_field(name="Button Emoji", value=step6, inline=False)

        step8 = "Add a message the bot sends to the user in their ticket.\n"
        step8 += f"`{ctx.clean_prefix}tickets addmessage`"
        em.add_field(name="Ticket Messages", value=step8, inline=False)

        step9 = "View and remove a messages the bot sends to the user in their ticket.\n"
        step9 += f"`{ctx.clean_prefix}tickets viewmessages`"
        em.add_field(name="Remove/View Ticket Messages", value=step9, inline=False)

        step10 = "Set the naming format for ticket channels that are opened.\n"
        step10 += f"`{ctx.clean_prefix}tickets ticketname <name_format>`"
        em.add_field(name="Ticket Channel Name", value=step10, inline=False)

        step11 = "Set log channel for tickets.\n"
        step11 += f"`{ctx.clean_prefix}tickets logchannel <channel>`"
        em.add_field(name="Log Channel", value=step11, inline=False)

        await ctx.send(embed=em)

    @tickets.command()
    async def suspend(self, ctx: commands.Context, *, message: Optional[str] = None):
        """
        Suspend the ticket system
        If a suspension message is set, any user that tries to open a ticket will receive this message
        """
        suspended = await self.config.guild(ctx.guild).suspended_msg()
        if message is None and suspended is None:
            return await ctx.send_help()
        if not message:
            await self.config.guild(ctx.guild).suspended_msg.set(None)
            return await ctx.send("Ticket system is no longer suspended!")
        if len(message) > 900:
            return await ctx.send("Message is too long! Must be less than 900 characters")
        await self.config.guild(ctx.guild).suspended_msg.set(message)
        embed = discord.Embed(
            title="Ticket System Suspended",
            description=message,
            color=discord.Color.yellow(),
        )
        await ctx.send(
            "Ticket system is now suspended! Users trying to open a ticket will be met with this message",
            embed=embed,
        )

    @tickets.command()
    async def category(self, ctx: commands.Context, category: discord.CategoryChannel):
        """Set the category ID for tickets"""
        if not category.permissions_for(ctx.me).manage_channels:
            return await ctx.send("I need the `manage channels` permission to set this category")
        if not category.permissions_for(ctx.me).manage_permissions:
            return await ctx.send("I need `manage roles` enabled in this category")
        if not category.permissions_for(ctx.me).attach_files:
            return await ctx.send("I need the `attach files` permission to set this category")
        if not category.permissions_for(ctx.me).view_channel:
            return await ctx.send("I cannot see that category!")
        if not category.permissions_for(ctx.me).read_message_history:
            return await ctx.send("I cannot see message history in that category!")
        
        await self.config.guild(ctx.guild).category_id.set(category.id)
        await ctx.tick()
        await ctx.send("New tickets will now be opened under that category!")

    @tickets.command()
    async def channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel ID where the ticket panel is located"""
        if not channel.permissions_for(ctx.guild.me).view_channel:
            return await ctx.send("I cannot see that channel!")
        if not channel.permissions_for(ctx.guild.me).read_message_history:
            return await ctx.send("I cannot see message history in that channel!")
        
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.tick()

    @tickets.command()
    async def panelmessage(self, ctx: commands.Context, message: discord.Message):
        """
        Set the message ID of the ticket panel
        Run this command in the same channel as the ticket panel message
        """
        if message.author.id != self.bot.user.id:
            return await ctx.send("I cannot add buttons to messages sent by other users!")
        if isinstance(
            message.channel,
            (discord.Thread, discord.VoiceChannel, discord.ForumChannel),
        ):
            return await ctx.send("Channel of message must be a TEXT CHANNEL!")
        
        category_id = await self.config.guild(ctx.guild).category_id()
        if not category_id:
            return await ctx.send("Category ID must be set first!")
            
        current_channel = await self.config.guild(ctx.guild).channel_id()
        if current_channel and current_channel != message.channel.id:
            return await ctx.send("This message is part of a different channel from the one you set!")
            
        await self.config.guild(ctx.guild).message_id.set(message.id)
        await self.config.guild(ctx.guild).channel_id.set(message.channel.id)
        await ctx.tick()
        await self.initialize(ctx.guild)

    @tickets.command()
    async def buttontext(self, ctx: commands.Context, *, button_text: str):
        """Set the button text for the ticket panel"""
        if len(button_text) > 80:
            return await ctx.send("The text content of a button must be less than 80 characters!")
        butt = TestButton(label=button_text)
        await ctx.send(
            "This is what your button will look like with this text!",
            view=butt,
        )
        await self.config.guild(ctx.guild).button_text.set(button_text)
        await ctx.tick()
        await self.initialize(ctx.guild)

    @tickets.command()
    async def buttoncolor(self, ctx: commands.Context, *, button_color: str):
        """Set the button color for the ticket panel"""
        button_color = button_color.lower()
        valid = ["red", "blue", "green", "grey", "gray"]
        if button_color not in valid:
            return await ctx.send(f"{button_color} is not valid, must be one of the following\n`{valid}`")
        butt = TestButton(style=button_color)
        await ctx.send(
            "This is what your button will look like with this color!",
            view=butt,
        )
        await self.config.guild(ctx.guild).button_color.set(button_color)
        await ctx.tick()
        await self.initialize(ctx.guild)

    @tickets.command()
    async def buttonemoji(
        self,
        ctx: commands.Context,
        *,
        emoji: Union[discord.Emoji, discord.PartialEmoji, str],
    ):
        """Set the button emoji for the ticket panel"""
        try:
            butt = TestButton(emoji=emoji)
            await ctx.send(
                "This is what your button will look like with this emoji!",
                view=butt,
            )
        except Exception as e:
            return await ctx.send(f"Failed to create test button. Error:\n{box(str(e), lang='python')}")
            
        await self.config.guild(ctx.guild).button_emoji.set(str(emoji))
        await ctx.tick()
        await self.initialize(ctx.guild)

    @tickets.command()
    async def ticketname(self, ctx: commands.Context, *, ticket_name: str):
        """
        Set the default ticket channel name
        
        You can include the following in the name:
        `{num}` - Ticket number
        `{user}` - user's name
        `{displayname}` - user's display name
        `{id}` - user's ID
        `{shortdate}` - mm-dd
        `{longdate}` - mm-dd-yyyy
        `{time}` - hh-mm AM/PM according to bot host system time
        
        You can set this to {default} to use default "Ticket-Username"
        """
        ticket_name = ticket_name.lower()
        await self.config.guild(ctx.guild).ticket_name.set(ticket_name)
        await ctx.tick()
        await self.initialize(ctx.guild)

    @tickets.command()
    async def logchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the logging channel for tickets"""
        if not channel.permissions_for(ctx.guild.me).view_channel:
            return await ctx.send("I cannot see that channel!")
        if not channel.permissions_for(ctx.guild.me).read_message_history:
            return await ctx.send("I cannot see message history in that channel!")
        if not channel.permissions_for(ctx.guild.me).send_messages:
            return await ctx.send("I cannot send messages in that channel!")
        if not channel.permissions_for(ctx.guild.me).embed_links:
            return await ctx.send("I cannot embed links in that channel!")
        if not channel.permissions_for(ctx.guild.me).attach_files:
            return await ctx.send("I cannot attach files in that channel!")
            
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.tick()
        await self.initialize(ctx.guild)

    @tickets.command()
    async def modaltitle(self, ctx: commands.Context, *, title: str = ""):
        """Set a title for the ticket modal"""
        if len(title) > 45:
            return await ctx.send("The max length is 45!")
        
        if title:
            await self.config.guild(ctx.guild).modal_title.set(title)
            await ctx.send("Modal title set!")
        else:
            await self.config.guild(ctx.guild).modal_title.set("")
            await ctx.send("Modal title removed!")
        await self.initialize(ctx.guild)

    @tickets.command()
    async def addmodal(self, ctx: commands.Context, field_name: str):
        """
        Add a modal field to the ticket panel
        
        Ticket panels can have up to 5 fields per modal for the user to fill out before opening a ticket.
        If modal fields are added and have required fields,
        the user will have to fill them out before they can open a ticket.
        
        **Note**
        `field_name` is just the name of the field stored in config,
        it won't be shown in the modal and should not have spaces in it
        
        Specify an existing field name to delete a modal field (non-case-sensitive)
        """
        field_name = field_name.lower()
        await self.create_or_edit_modal(ctx, field_name)

    async def create_or_edit_modal(
        self,
        ctx: commands.Context,
        field_name: str,
        existing_modal: Optional[dict] = None,
        preview: Optional[discord.Message] = None,
    ):
        if not existing_modal:
            # User wants to add or delete a field
            modal_data = await self.config.guild(ctx.guild).modal()
            if field_name in modal_data:
                # Delete field
                async with self.config.guild(ctx.guild).modal() as m:
                    del m[field_name]
                return await ctx.send(f"Field {field_name} has been removed!")

            if len(modal_data) >= 5:
                return await ctx.send("The most fields a modal can have is 5!")

        async def make_preview(m, mm: discord.Message):
            txt = ""
            for k, v in m.items():
                if k == "answer":
                    continue
                txt += f"{k}: {v}\n"
            title = "Modal Preview"
            await mm.edit(
                embed=discord.Embed(title=title, description=box(txt), color=color),
                view=None,
            )

        async def cancel(m):
            await m.edit(embed=discord.Embed(description="Modal field addition cancelled", color=color))

        foot = "type 'cancel' to cancel at any time"
        color = ctx.author.color

        modal = MODAL_SCHEMA.copy() if not existing_modal else existing_modal
        if preview:
            await make_preview(modal, preview)

        # Label
        em = Embed(
            description="What would you like the field label to be? (45 chars or less)",
            color=color,
        )
        em.set_footer(text=foot)
        msg = await ctx.send(embed=em)
        label = await wait_reply(ctx, 300, False)
        if not label:
            return await cancel(msg)
        if len(label) > 45:
            em = Embed(
                description="Modal field labels must be 45 characters or less!",
                color=color,
            )
            return await msg.edit(embed=em)
        modal["label"] = label

        if not preview:
            preview = msg

        await make_preview(modal, preview)

        # Style
        em = Embed(
            description="What style would you like the text box to be? (long/short)",
            color=color,
        )
        em.set_footer(text=foot)
        msg = await ctx.send(embed=em)
        style = await wait_reply(ctx, 300, False)
        if not style:
            return await cancel(msg)
        if style not in ["long", "short"]:
            em = Embed(
                description="Style must be long or short!",
                color=color,
            )
            return await msg.edit(embed=em)
        modal["style"] = style
        await make_preview(modal, preview)

        # Placeholder
        em = Embed(
            description=(
                "Would you like to set a placeholder for the text field?\n"
                "This is text that shows up in the box before the user types."
            ),
            color=color,
        )
        await msg.edit(embed=em)
        yes = await confirm(ctx, msg)
        if yes is None:
            return
        if yes:
            em = Embed(
                description="Type your desired placeholder below (100 chars max)",
                color=color,
            )
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            placeholder = await wait_reply(ctx, 300, False)
            if not placeholder:
                return await cancel(msg)
            if len(placeholder) > 100:
                em = Embed(
                    description="Placeholders must be 100 characters or less!",
                    color=discord.Color.red(),
                )
                return await msg.edit(embed=em)
            modal["placeholder"] = placeholder
            await make_preview(modal, preview)

        # Default
        em = Embed(
            description="Would you like to set a default value for the text field?",
            color=color,
        )
        await msg.edit(embed=em)
        yes = await confirm(ctx, msg)
        if yes is None:
            return
        if yes:
            em = Embed(
                description="Type your desired default value below",
                color=color,
            )
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            default = await wait_reply(ctx, 300, False)
            if not default:
                return await cancel(msg)
            modal["default"] = default
            await make_preview(modal, preview)

        # Required?
        em = Embed(
            description="Would you like to make this field required?",
            color=color,
        )
        await msg.edit(embed=em)
        yes = await confirm(ctx, msg)
        if yes is None:
            return
        if not yes:
            modal["required"] = False
            await make_preview(modal, preview)

        # Min length
        em = Embed(
            description="Would you like to set a minimum length for this field?",
            color=color,
        )
        await msg.edit(embed=em)
        yes = await confirm(ctx, msg)
        if yes is None:
            return
        min_length = 0
        if yes:
            em = Embed(
                description="Type the minimum length for this field below (less than 1024)",
                color=color,
            )
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            min_length = await wait_reply(ctx, 300, False)
            if not min_length:
                return await cancel(msg)
            if not min_length.isdigit():
                em = Embed(
                    description="That is not a number!",
                    color=discord.Color.red(),
                )
                return await msg.edit(embed=em)
            min_length = min(1023, int(min_length))
            modal["min_length"] = min_length
            await make_preview(modal, preview)

        # Max length
        em = Embed(
            description="Would you like to set a maximum length for this field?",
            color=color,
        )
        await msg.edit(embed=em)
        yes = await confirm(ctx, msg)
        if yes is None:
            return
        if yes:
            em = Embed(
                description="Type the maximum length for this field below (up to 1024)",
                color=color,
            )
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            maxlength = await wait_reply(ctx, 300, False)
            if not maxlength:
                return await cancel(msg)
            if not maxlength.isdigit():
                em = discord.Embed(
                    description="That is not a number!",
                    color=discord.Color.red(),
                )
                return await msg.edit(embed=em)
            max_length = max(min(1024, int(maxlength)), 1)
            if max_length < min_length:
                em = Embed(
                    description="Max length cannot be less than the minimum length",
                    color=discord.Color.red(),
                )
                return await msg.edit(embed=em)

            modal["max_length"] = max_length
            await make_preview(modal, preview)

        async with self.config.guild(ctx.guild).modal() as m:
            m[field_name] = modal

        await ctx.tick()
        desc = "Your modal field has been added!"
        if existing_modal:
            desc = "Your modal field has been edited!"
        em = Embed(
            description=desc,
            color=discord.Color.green(),
        )
        await msg.edit(embed=em)
        await self.initialize(ctx.guild)

    @tickets.command()
    async def viewmodal(self, ctx: commands.Context):
        """View/Delete modal fields"""
        modal = await self.config.guild(ctx.guild).modal()
        if not modal:
            return await ctx.send("Ticket system does not have any modal fields set!")
        embeds = []
        for i, fieldname in enumerate(list(modal.keys())):
            info = modal[fieldname]
            txt = f"`Label: `{info['label']}\n"
            txt += f"`Style: `{info['style']}\n"
            txt += f"`Placeholder: `{info['placeholder']}\n"
            txt += f"`Default:     `{info['default']}\n"
            txt += f"`Required:    `{info['required']}\n"
            txt += f"`Min Length:  `{info['min_length']}\n"
            txt += f"`Max Length:  `{info['max_length']}\n"

            desc = f"**{fieldname}**\n{txt}\n"
            desc += f"Page `{i + 1}/{len(list(modal.keys()))}`"

            em = Embed(
                title="Modal Fields",
                description=desc,
                color=ctx.author.color,
            )
            em.set_footer(text=f"{fieldname}")
            embeds.append(em)

        controls = SMALL_CONTROLS.copy()
        controls["\N{WASTEBASKET}\N{VARIATION SELECTOR-16}"] = self.delete_modal_field
        controls["\N{MEMO}"] = self.edit_modal_field
        await menu(ctx, embeds, controls)

    async def edit_modal_field(self, instance, interaction: discord.Interaction):
        index = instance.view.page
        em: Embed = instance.view.pages[index]
        fieldname = em.footer.text
        modal_data = await self.config.guild(interaction.guild).modal()
        modal = modal_data[fieldname]
        em = Embed(description=f"Editing {fieldname} modal field!")
        await interaction.response.send_message(embed=em, ephemeral=True)
        instance.view.stop()
        await self.create_or_edit_modal(instance.view.ctx, fieldname, modal)

    async def delete_modal_field(self, instance: MenuButton, interaction: discord.Interaction):
        index = instance.view.page
        em: Embed = instance.view.pages[index]
        fieldname = em.footer.text
        async with self.config.guild(interaction.guild).modal() as modal:
            del modal[fieldname]

        em = Embed(description=f"Modal field {fieldname} has been deleted!")
        await interaction.response.send_message(embed=em, ephemeral=True)
        del instance.view.pages[index]
        if not len(instance.view.pages):
            em = Embed(description="There are no more modal fields")
            await interaction.followup.send(embed=em, ephemeral=True)
            instance.view.stop()
            return await instance.view.message.delete()
        instance.view.page += 1
        instance.view.page %= len(instance.view.pages)
        for i, embed in enumerate(instance.view.pages):
            # No page number in footer in this simplified version, but logic tries to keep consistent
            pass 
        return await menu(
            instance.view.ctx,
            instance.view.pages,
            instance.view.controls,
            instance.view.message,
            instance.view.page,
        )

    @tickets.command()
    async def addmessage(self, ctx: commands.Context):
        """
        Add a message embed to be sent when a ticket is opened
        
        You can include any of these in the embed to be replaced by their value when the message is sent
        `{username}` - Person's Discord username
        `{mention}` - This will mention the user
        `{id}` - This is the ID of the user that created the ticket
        
        The bot will walk you through a few steps to set up the embed.
        """
        foot = "type 'cancel' to cancel the setup"
        color = ctx.author.color
        # TITLE
        em = Embed(
            description="Would you like this ticket embed to have a title?",
            color=color,
        )
        msg = await ctx.send(embed=em)
        yes = await confirm(ctx, msg)
        if yes is None:
            return
        if yes:
            em = Embed(description="Type your desired title below", color=color)
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            title = await wait_reply(ctx, 300)
            if title and title.lower().strip() == "cancel":
                em = Embed(description="Ticket message addition cancelled")
                return await msg.edit(embed=em)
        else:
            title = None
        # BODY
        em = Embed(
            description="Type your desired ticket message below",
            color=color,
        )
        em.set_footer(text=foot)
        await msg.edit(embed=em)
        desc = await wait_reply(ctx, 600)
        if desc and desc.lower().strip() == "cancel":
            em = Embed(description="Ticket message addition cancelled")
            return await msg.edit(embed=em)
        if desc is None:
            em = Embed(description="Ticket message addition cancelled")
            return await msg.edit(embed=em)
        # FOOTER
        em = Embed(
            description="Would you like this ticket embed to have a footer?",
            color=color,
        )
        await msg.edit(embed=em)
        yes = await confirm(ctx, msg)
        if yes is None:
            return
        if yes:
            em = Embed(description="Type your footer", color=color)
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            footer = await wait_reply(ctx, 300)
            if footer and footer.lower().strip() == "cancel":
                em = Embed(description="Ticket message addition cancelled")
                return await msg.edit(embed=em)
        else:
            footer = None

        # CUSTOM COLOR
        em = Embed(
            description="Would you like this ticket embed to have a custom color?",
            color=color,
        )
        await msg.edit(embed=em)
        yes = await confirm(ctx, msg)
        if yes is None:
            return
        embed_color = None
        if yes:
            em = Embed(
                description="Enter a hex color code (e.g., #FF0000 for red, #00FF00 for green)",
                color=color,
            )
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            color_input = await wait_reply(ctx, 300)
            if color_input and color_input.lower().strip() == "cancel":
                em = Embed(description="Ticket message addition cancelled")
                return await msg.edit(embed=em)
            if color_input:
                color_input = color_input.strip().lstrip("#")
                try:
                    embed_color = int(color_input, 16)
                    if embed_color < 0 or embed_color > 0xFFFFFF:
                        em = Embed(description="Invalid color value! Using default color.", color=color)
                        await ctx.send(embed=em, delete_after=5)
                        embed_color = None
                except ValueError:
                    em = Embed(description="Invalid hex color format! Using default color.", color=color)
                    await ctx.send(embed=em, delete_after=5)
                    embed_color = None

        # IMAGE
        em = Embed(
            description="Would you like this ticket embed to have an image?",
            color=color,
        )
        await msg.edit(embed=em)
        yes = await confirm(ctx, msg)
        if yes is None:
            return
        image = None
        if yes:
            em = Embed(description="Enter the image URL", color=color)
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            image = await wait_reply(ctx, 300)
            if image and image.lower().strip() == "cancel":
                em = Embed(description="Ticket message addition cancelled")
                return await msg.edit(embed=em)

        embed = {"title": title, "desc": desc, "footer": footer, "color": embed_color, "image": image}

        async with self.config.guild(ctx.guild).ticket_messages() as messages:
            messages.append(embed)
            
        await ctx.tick()
        em = Embed(description="Your ticket message has been added!")
        await msg.edit(embed=em)
        await self.initialize(ctx.guild)

    @tickets.command()
    async def viewmessages(self, ctx: commands.Context):
        """View/Delete ticket messages"""
        messages = await self.config.guild(ctx.guild).ticket_messages()
        if not messages:
            return await ctx.send("Ticket system does not have any messages added!")
        embeds = []
        for i, msg in enumerate(messages):
            desc = "**Title**\n" + box(msg["title"]) + "\n"
            desc += "**Description**\n" + box(msg["desc"]) + "\n"
            desc += "**Footer**\n" + box(msg["footer"]) + "\n"
            
            color_val = msg.get("color")
            if color_val is not None and isinstance(color_val, int):
                desc += "**Color**\n" + box(f"#{color_val:06X}") + "\n"
            else:
                desc += "**Color**\n" + box("Default (user's color)") + "\n"
                
            image_val = msg.get("image")
            desc += "**Image**\n" + box(image_val if image_val else "None")
            
            em = Embed(
                title="Ticket Messages",
                description=desc,
                color=discord.Color(color_val) if color_val is not None and isinstance(color_val, int) else ctx.author.color,
            )
            if image_val:
                em.set_image(url=image_val)
            em.set_footer(text=f"Page {i + 1}/{len(messages)}")
            embeds.append(em)

        controls = SMALL_CONTROLS.copy()
        controls["\N{WASTEBASKET}\N{VARIATION SELECTOR-16}"] = self.delete_panel_message
        await menu(ctx, embeds, controls)

    async def delete_panel_message(self, instance, interaction: discord.Interaction):
        index = instance.view.page
        async with self.config.guild(interaction.guild).ticket_messages() as messages:
            del messages[index]
            
        em = Embed(description="Ticket message has been deleted!")
        await interaction.response.send_message(embed=em, ephemeral=True)
        del instance.view.pages[index]
        if not len(instance.view.pages):
            em = Embed(description="There are no more messages")
            return await interaction.followup.send(embed=em, ephemeral=True)
        instance.view.page += 1
        instance.view.page %= len(instance.view.pages)
        for i, embed in enumerate(instance.view.pages):
            embed.set_footer(text=f"Page {i + 1}/{len(instance.view.pages)}")
        await instance.view.handle_page(interaction.response.edit_message)

    @tickets.command(name="view")
    async def view_settings(self, ctx: commands.Context):
        """View support ticket settings"""
        conf = await self.config.guild(ctx.guild).all()
        inactive = conf["inactive"]
        plural = "hours"
        singular = "hour"
        no_resp = f"{inactive} {singular if inactive == 1 else plural}"
        if not inactive:
            no_resp = "Disabled"

        msg = f"`Max Tickets:      `{conf['max_tickets']}\n"
        msg += f"`DM Alerts:        `{conf['dm']}\n"
        msg += f"`Users can Rename: `{conf['user_can_rename']}\n"
        msg += f"`Users can Close:  `{conf['user_can_close']}\n"
        msg += f"`Users can Manage: `{conf['user_can_manage']}\n"
        msg += f"`Auto Close:       `{'On' if inactive else 'Off'}\n"
        msg += f"`NoResponseDelete: `{no_resp}\n"

        # Support Roles
        support = conf["support_roles"]
        suproles = ""
        if support:
            for role_id, mention_toggle in support:
                role = ctx.guild.get_role(role_id)
                if role:
                    suproles += f"{role.mention}({mention_toggle})\n"

        # Blacklist
        blacklist = conf["blacklist"]
        blacklisted = ""
        if blacklist:
            for uid_or_rid in blacklist:
                user_or_role = ctx.guild.get_member(uid_or_rid) or ctx.guild.get_role(uid_or_rid)
                if user_or_role:
                    blacklisted += f"{user_or_role.mention}-{user_or_role.id}\n"
                else:
                    blacklisted += f"Invalid-{uid_or_rid}\n"
                    
        embed = Embed(
            title="Tickets Core Settings",
            description=msg,
            color=discord.Color.random(),
        )
        if suproles:
            embed.add_field(name="Support Roles(Mention)", value=suproles, inline=False)
        if blacklisted:
            embed.add_field(name="Blacklist", value=blacklisted, inline=False)

        # Suspended Message
        if conf["suspended_msg"]:
            embed.add_field(
                name="Suspended Message",
                value=f"Tickets are currently suspended, users will be met with the following message\n{box(conf['suspended_msg'])}",
                inline=False,
            )
            
        # Panel Info (Flattened)
        cat = self.bot.get_channel(conf["category_id"]) if conf["category_id"] else "None"
        channel = self.bot.get_channel(conf["channel_id"]) if conf["channel_id"] else "None"
        logchannel = self.bot.get_channel(conf["log_channel"]) if conf["log_channel"] else "None"
        
        panel_desc = f"`Category:       `{cat}\n"
        panel_desc += f"`Channel:        `{channel}\n"
        panel_desc += f"`MessageID:      `{conf['message_id']}\n"
        panel_desc += f"`ButtonText:     `{conf['button_text']}\n"
        panel_desc += f"`ButtonColor:    `{conf['button_color']}\n"
        panel_desc += f"`ButtonEmoji:    `{conf['button_emoji']}\n"
        panel_desc += f"`TicketMessages: `{len(conf['ticket_messages'])}\n"
        panel_desc += f"`TicketName:     `{conf['ticket_name']}\n"
        panel_desc += f"`Modal Fields:   `{len(conf.get('modal', {}))}\n"
        panel_desc += f"`Modal Title:    `{conf.get('modal_title', 'None')}\n"
        panel_desc += f"`LogChannel:     `{logchannel}\n"
        
        embed.add_field(name="Panel Settings", value=panel_desc, inline=False)
        
        # Required Roles
        req_roles = ""
        for role_id in conf.get("required_roles", []):
            role = ctx.guild.get_role(role_id)
            if role:
                req_roles += f"{role.mention}\n"
        if req_roles:
            embed.add_field(name="Required Roles to Open", value=req_roles, inline=False)

        await ctx.send(embed=embed)

    @tickets.command()
    async def maxtickets(self, ctx: commands.Context, amount: int):
        """Set the max tickets a user can have open at one time of any kind"""
        if not amount:
            return await ctx.send("Max ticket amount must be greater than 0!")
        await self.config.guild(ctx.guild).max_tickets.set(amount)
        await ctx.tick()

    @tickets.command()
    async def supportrole(
        self,
        ctx: commands.Context,
        role: discord.Role,
        mention: Optional[bool] = False,
    ):
        """
        Add/Remove ticket support roles (one at a time)
        
        **Optional**: include `true` for mention to have that role mentioned when a ticket is opened
        
        To remove a role, simply run this command with it again to remove it
        """
        entry = [role.id, mention]
        async with self.config.guild(ctx.guild).support_roles() as roles:
            for i in roles.copy():
                if i[0] == role.id:
                    roles.remove(i)
                    await ctx.send(f"{role.name} has been removed from support roles")
                    break
            else:
                roles.append(entry)
                await ctx.send(f"{role.name} has been added to support roles")
        await self.initialize(ctx.guild)

    @tickets.command()
    async def openrole(self, ctx: commands.Context, *, role: discord.Role):
        """
        Add/Remove roles required to open a ticket
        
        Specify the same role to remove it
        """
        async with self.config.guild(ctx.guild).required_roles() as roles:
            if role.id in roles:
                roles.remove(role.id)
                await ctx.send(f"{role.name} has been removed from required open roles")
            else:
                roles.append(role.id)
                await ctx.send(f"{role.name} has been added to required open roles")
        await self.initialize(ctx.guild)

    @tickets.command()
    async def blacklist(
        self,
        ctx: commands.Context,
        *,
        user_or_role: Union[discord.Member, discord.Role],
    ):
        """
        Add/Remove users or roles from the blacklist
        
        Users and roles in the blacklist will not be able to create a ticket
        """
        async with self.config.guild(ctx.guild).blacklist() as bl:
            if user_or_role.id in bl:
                bl.remove(user_or_role.id)
                await ctx.send(f"{user_or_role.name} has been removed from the blacklist")
            else:
                bl.append(user_or_role.id)
                await ctx.send(f"{user_or_role.name} has been added to the blacklist")

    @tickets.command()
    async def noresponse(self, ctx: commands.Context, hours: int):
        """
        Auto-close ticket if opener doesn't say anything after X hours of opening
        
        Set to 0 to disable this
        """
        await self.config.guild(ctx.guild).inactive.set(hours)
        await ctx.tick()

    @tickets.command()
    async def overview(
        self,
        ctx: commands.Context,
        *,
        channel: Optional[discord.TextChannel] = None,
    ):
        """
        Set a channel for the live overview message
        
        The overview message shows all active tickets.
        """
        if not channel:
            await ctx.send("Overview channel has been **Disabled**")
            await self.config.guild(ctx.guild).overview_channel.set(0)
        else:
            await ctx.send(f"Overview channel has been set to {channel.mention}")
            await self.config.guild(ctx.guild).overview_channel.set(channel.id)
            conf = await self.config.guild(ctx.guild).all()
            new_id = await update_active_overview(ctx.guild, conf)
            if new_id:
                await self.config.guild(ctx.guild).overview_msg.set(new_id)

    @tickets.command()
    async def overviewmention(self, ctx: commands.Context):
        """Toggle whether channels are mentioned in the active ticket overview"""
        toggle = await self.config.guild(ctx.guild).overview_mention()
        if toggle:
            await self.config.guild(ctx.guild).overview_mention.set(False)
            txt = "Ticket channels will no longer be mentioned in the active ticket channel"
        else:
            await self.config.guild(ctx.guild).overview_mention.set(True)
            txt = "Ticket channels now be mentioned in the active ticket channel"
        await ctx.send(txt)

    @tickets.command()
    async def cleanup(self, ctx: commands.Context):
        """Cleanup tickets that no longer exist"""
        async with ctx.typing():
            conf = await self.config.guild(ctx.guild).all()
            await prune_invalid_tickets(ctx.guild, conf, self.config, ctx)

    # TOGGLES --------------------------------------------------------------------------------
    @tickets.command()
    async def dm(self, ctx: commands.Context):
        """(Toggle) The bot sending DM's for ticket alerts"""
        toggle = await self.config.guild(ctx.guild).dm()
        if toggle:
            await self.config.guild(ctx.guild).dm.set(False)
            await ctx.send("DM alerts have been **Disabled**")
        else:
            await self.config.guild(ctx.guild).dm.set(True)
            await ctx.send("DM alerts have been **Enabled**")

    @tickets.command()
    async def selfrename(self, ctx: commands.Context):
        """(Toggle) If users can rename their own tickets"""
        toggle = await self.config.guild(ctx.guild).user_can_rename()
        if toggle:
            await self.config.guild(ctx.guild).user_can_rename.set(False)
            await ctx.send("User can no longer rename their support channel")
        else:
            await self.config.guild(ctx.guild).user_can_rename.set(True)
            await ctx.send("User can now rename their support channel")

    @tickets.command()
    async def selfclose(self, ctx: commands.Context):
        """(Toggle) If users can close their own tickets"""
        toggle = await self.config.guild(ctx.guild).user_can_close()
        if toggle:
            await self.config.guild(ctx.guild).user_can_close.set(False)
            await ctx.send("User can no longer close their support ticket channel")
        else:
            await self.config.guild(ctx.guild).user_can_close.set(True)
            await ctx.send("User can now close their support ticket channel")

    @tickets.command()
    async def selfmanage(self, ctx: commands.Context):
        """
        (Toggle) If users can manage their own tickets
        
        Users will be able to add/remove others to their support ticket
        """
        toggle = await self.config.guild(ctx.guild).user_can_manage()
        if toggle:
            await self.config.guild(ctx.guild).user_can_manage.set(False)
            await ctx.send("User can no longer manage their support ticket channel")
        else:
            await self.config.guild(ctx.guild).user_can_manage.set(True)
            await ctx.send("User can now manage their support ticket channel")

    @tickets.command()
    async def updatemessage(
        self,
        ctx: commands.Context,
        source: discord.Message,
        target: discord.Message,
    ):
        """Update a message with another message (Target gets updated using the source)"""
        try:
            await target.edit(
                embeds=source.embeds,
                content=target.content,
                attachments=target.attachments,
            )
            await ctx.tick()
        except discord.HTTPException as e:
            if txt := e.text:
                await ctx.send(txt)
            else:
                await ctx.send("Failed to update message!")

    @tickets.command()
    async def embed(
        self,
        ctx: commands.Context,
        color: Optional[discord.Color],
        channel: Optional[discord.TextChannel],
        title: str,
        *,
        description: str,
    ):
        """Create an embed for ticket panel buttons to be added to"""
        foot = "type 'cancel' to cancel"
        channel = channel or ctx.channel
        color = color or ctx.author.color
        # FOOTER
        em = Embed(
            description="Would you like this embed to have a footer?",
            color=color,
        )
        msg = await ctx.send(embed=em)
        yes = await confirm(ctx, msg)
        if yes:
            em = Embed(description="Enter the desired footer", color=color)
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            footer = await wait_reply(ctx, 300)
            if footer and footer.lower().strip() == "cancel":
                em = Embed(description="Embed creation cancelled")
                return await msg.edit(embed=em)
        else:
            footer = None

        # Thumbnail
        em = Embed(
            description="Would you like this embed to have a thumbnail?",
            color=color,
        )
        try:
            await msg.edit(embed=em)
        except discord.NotFound:
            # Message was deleted. Just cancel.
            return
        yes = await confirm(ctx, msg)
        if yes is None:
            return

        if yes:
            em = Embed(description="Enter a url for the thumbnail", color=color)
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            thumbnail = await wait_reply(ctx, 300)
            if thumbnail and thumbnail.lower().strip() == "cancel":
                em = Embed(description="Embed creation cancelled")
                return await msg.edit(embed=em)
        else:
            thumbnail = None

        # Image
        em = Embed(
            description="Would you like this embed to have an image?",
            color=color,
        )
        await msg.edit(embed=em)
        yes = await confirm(ctx, msg)
        if yes:
            em = Embed(description="Enter a url for the image", color=color)
            em.set_footer(text=foot)
            await msg.edit(embed=em)
            image = await wait_reply(ctx, 300)
            if image and image.lower().strip() == "cancel":
                em = Embed(description="Embed creation cancelled")
                return await msg.edit(embed=em)
        else:
            image = None

        embed = discord.Embed(title=title, description=description, color=color)
        if footer:
            embed.set_footer(text=footer)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        if image:
            embed.set_image(url=image)

        fields = 0
        while fields < 25:
            if not fields:
                em = Embed(
                    description="Would you like to add a field to this embed?",
                    color=color,
                )
            else:
                em = Embed(
                    description=(
                        f"Would you like to add another field to this embed?\n*There are currently {fields} fields*"
                    ),
                    color=color,
                )
            await msg.edit(embed=em)
            yes = await confirm(ctx, msg)
            if yes:
                em = Embed(description="Enter the name of the field", color=color)
                em.set_footer(text=foot)
                await msg.edit(embed=em)
                name = await wait_reply(ctx, 300)
                if name and name.lower().strip() == "cancel":
                    break
                em = Embed(description="Enter the value of the field", color=color)
                em.set_footer(text=foot)
                await msg.edit(embed=em)
                value = await wait_reply(ctx, 300)
                if value and value.lower().strip() == "cancel":
                    break
                em = Embed(
                    description="Do you want this field to be inline?",
                    color=color,
                )
                await msg.edit(embed=em)
                yes = await confirm(ctx, msg)
                inline = True if yes else False
                embed.add_field(name=name, value=value, inline=inline)
                fields += 1
            else:
                break

        try:
            await channel.send(embed=embed)
            await msg.edit(content="Your embed has been sent!", embed=None)
        except Exception as e:
            await ctx.send(f"Failed to send embed!\nException: {box(str(e), 'py')}")

    @commands.hybrid_command(name="openfor")
    @commands.mod_or_permissions(manage_messages=True)
    async def openfor(self, ctx: commands.Context, user: discord.Member):
        """Open a ticket for another user"""
        conf = await self.config.guild(ctx.guild).all()
        # Create a custom temp view by using the config directly
        
        panel_data = {
            "category_id": conf["category_id"],
            "channel_id": conf["channel_id"],
            "message_id": conf["message_id"],
            "button_text": conf["button_text"],
            "button_color": conf["button_color"],
            "button_emoji": conf["button_emoji"],
            "ticket_messages": conf["ticket_messages"],
            "ticket_name": conf["ticket_name"],
            "log_channel": conf["log_channel"],
            "modal": conf.get("modal", {}),
            "modal_title": conf.get("modal_title", ""),
            "ticket_num": conf.get("ticket_num", 1),
            "disabled": False, # Implicitly enabled
            "priority": 1,
            "row": 0,
            "roles": [], # Panel roles now merged into support roles or handled differently?
            # Actually support roles are global now.
        }
        
        # PanelView signature: (bot, guild, config, conf, mock_user=None)
        view = PanelView(self.bot, ctx.guild, self.config, panel_data, mock_user=user)
        desc = (
            f"Click the button below to open a ticket for {user.name}\n"
            "This message will self-cleanup in 2 minutes."
        )
        embed = discord.Embed(description=desc, color=await self.bot.get_embed_color(ctx))
        await ctx.send(embed=embed, view=view, delete_after=120)
        await asyncio.sleep(120)
        if not ctx.interaction:
            await ctx.tick()
