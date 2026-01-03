import asyncio
import logging
from datetime import datetime
from io import StringIO

import discord
from redbot.core import commands
from redbot.core.utils.chat_formatting import pagify

from ..abc import MixinMeta
from ..common.utils import update_active_overview

log = logging.getLogger("red.kirin_cogs.tickets.functions")


class Functions(MixinMeta):
    # @commands.Cog.listener()
    # async def on_assistant_cog_add(self, cog: commands.Cog):
    #     pass

    async def get_ticket_info(self, user: discord.Member, *args, **kwargs) -> str:
        """Fetch available ticket requirements that the user can open.
        Returns the ticket section requirements.

        Args:
            user (discord.Member): User that the ticket would be for.
        """
        guild = user.guild
        conf = await self.config.guild(guild).all()
        if conf["suspended_msg"]:
            return f"Tickets are suspended: {conf['suspended_msg']}"
        if user.id in conf["blacklist"]:
            return "This user has been blacklisted from opening tickets!"
        if any(r.id in conf["blacklist"] for r in user.roles):
            return "This user has a role that is blacklisted from opening tickets!"

        opened = conf["opened"]
        if str(user.id) in opened and conf["max_tickets"] <= len(opened[str(user.id)]):
            channels = "\n".join([f"<#{i}>" for i in opened[str(user.id)]])
            txt = f"This user has the maximum amount of tickets opened already!\nTickets: {channels}"
            return txt

        # Check if the channel exists
        channel = guild.get_channel(conf["channel_id"])
        if channel is None:
            return "Support system is currently not configured!"

        # Check if the member has the required roles
        required_roles = conf.get("required_roles", [])
        if required_roles and not any(role.id in required_roles for role in user.roles):
            return "User does not have required roles to open a ticket."

        buffer = StringIO()
        q = "Pre-ticket questions (USER MUST ANSWER THESE IN DETAIL BEFORE TICKET CAN BE OPENED!)\n"
        
        buffer.write("# Support Ticket System\n")
        if btext := conf["button_text"]:
            buffer.write(f"- Tag: {btext}\n")

        if modal := conf.get("modal"):
            if questions := list(modal.values()):
                buffer.write(q)
                for idx, i in enumerate(questions):
                    required = "(Required)" if i["required"] else "(Optional)"
                    buffer.write(f"- Question {idx + 1} {required}: {i['label']}\n")
                    if placeholder := i["placeholder"]:
                        buffer.write(f" - Example: {placeholder}\n")

        return buffer.getvalue()

    async def create_ticket_for_user(
        self,
        user: discord.Member,
        *args,
        **kwargs,
    ) -> str:
        """Create a ticket for the given member."""

        guild = user.guild
        conf = await self.config.guild(guild).all()
        if conf["suspended_msg"]:
            return f"Tickets are suspended: {conf['suspended_msg']}"

        logchannel = guild.get_channel(conf["log_channel"]) if conf["log_channel"] else None
        category = guild.get_channel(conf["category_id"]) if conf["category_id"] else None
        channel = guild.get_channel(conf["channel_id"]) if conf["channel_id"] else None

        if not category:
            return "The category for this panel is missing!"
        if not channel:
            return "The channel required for this ticket panel is missing!"

        # Check if the member has already reached the maximum number of open tickets allowed
        max_tickets = conf["max_tickets"]
        opened = conf["opened"]
        uid = str(user.id)
        if uid in opened and max_tickets <= len(opened[uid]):
            return "This user has reached the maximum number of open tickets allowed!"

        # Verify that the member has the required roles to open a ticket from the specified panel
        required_roles = conf.get("required_roles", [])
        if required_roles and not any(role.id in required_roles for role in user.roles):
            return "This user does not have the required roles to open this ticket."

        answers = {}
        form_embed = discord.Embed()

        can_read_send = discord.PermissionOverwrite(
            read_messages=True,
            read_message_history=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            use_application_commands=True,
        )
        read_and_manage = discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
            attach_files=True,
            embed_links=True,
            manage_channels=True,
            manage_messages=True,
        )

        support_roles = []
        support_mentions = []
        for role_id, mention_toggle in conf["support_roles"]:
            role = guild.get_role(role_id)
            if not role:
                continue
            support_roles.append(role)
            if mention_toggle:
                support_mentions.append(role.mention)

        overwrite = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: read_and_manage,
            user: can_read_send,
        }
        for role in support_roles:
            overwrite[role] = can_read_send

        num = conf["ticket_num"]
        now = datetime.now().astimezone()
        name_fmt = conf["ticket_name"]
        params = {
            "num": str(num),
            "user": user.name,
            "displayname": user.display_name,
            "id": str(user.id),
            "shortdate": now.strftime("%m-%d"),
            "longdate": now.strftime("%m-%d-%Y"),
            "time": now.strftime("%I-%M-%p"),
        }
        channel_name = name_fmt.format(**params) if name_fmt else user.name
        default_channel_name = f"ticket-{num}"
        try:
            try:
                channel_or_thread: discord.TextChannel = await category.create_text_channel(
                    channel_name, overwrites=overwrite
                )
            except Exception as e:
                if "Contains words not allowed" in str(e):
                    channel_or_thread = await category.create_text_channel(
                        default_channel_name, overwrites=overwrite
                    )
                    await channel_or_thread.send(
                        (
                            "I was not able to name the ticket properly due to Discord's filter!\nIntended name: {}"
                        ).format(channel_name)
                    )
                else:
                    raise e
        except discord.Forbidden:
            return "Missing requried permissions to create the ticket!"

        except Exception as e:
            log.error("Error creating ticket channel", exc_info=e)
            return f"ERROR: {e}"

        prefix = (await self.bot.get_valid_prefixes(guild))[0]
        default_message = "Welcome to your ticket channel " + f"{user.display_name}!"
        user_can_close = conf["user_can_close"]
        if user_can_close:
            default_message += "\nYou or an admin can close this with the `{}close` command".format(prefix)

        messages = conf["ticket_messages"]
        params = {
            "username": user.name,
            "displayname": user.display_name,
            "mention": user.mention,
            "id": str(user.id),
            "server": guild.name,
            "guild": guild.name,
            "members": int(guild.member_count or len(guild.members)),
            "toprole": user.top_role.name,
        }

        def fmt_params(text: str) -> str:
            for k, v in params.items():
                text = text.replace("{" + str(k) + "}", str(v))
            return text

        support_mentions.append(user.mention)
        content = " ".join(support_mentions)

        from ..common.views import CloseView

        allowed_mentions = discord.AllowedMentions(roles=True)
        close_view = CloseView(
            self.bot,
            self.config,
            user.id,
            channel_or_thread,
        )
        if messages:
            embeds = []
            for index, einfo in enumerate(messages):
                # Use custom color if set and valid, otherwise default to user's color
                color_val = einfo.get("color")
                embed_color = discord.Color(color_val) if color_val is not None and isinstance(color_val, int) else user.color
                em = discord.Embed(
                    title=fmt_params(einfo["title"]) if einfo["title"] else None,
                    description=fmt_params(einfo["desc"]),
                    color=embed_color,
                )
                if index == 0:
                    em.set_thumbnail(url=user.display_avatar.url)
                if einfo["footer"]:
                    em.set_footer(text=fmt_params(einfo["footer"]))
                # Set image if configured
                if einfo.get("image"):
                    em.set_image(url=einfo["image"])
                embeds.append(em)

            msg = await channel_or_thread.send(
                content=content, embeds=embeds, allowed_mentions=allowed_mentions, view=close_view
            )
        else:
            # Default message
            em = discord.Embed(description=default_message, color=user.color)
            em.set_thumbnail(url=user.display_avatar.url)
            msg = await channel_or_thread.send(
                content=content, embed=em, allowed_mentions=allowed_mentions, view=close_view
            )

        if logchannel:
            ts = int(now.timestamp())
            kwargs = {
                "user": str(user),
                "userid": user.id,
                "timestamp": f"<t:{ts}:R>",
                "channelname": channel_name,
                "jumpurl": msg.jump_url,
            }
            desc = (
                "`Created By: `{user}\n"
                "`User ID:    `{userid}\n"
                "`Opened:     `{timestamp}\n"
                "`Ticket:     `{channelname}\n"
                "**[Click to Jump!]({jumpurl})**"
            ).format(**kwargs)
            em = discord.Embed(
                title="Ticket Opened",
                description=desc,
                color=discord.Color.red(),
            )
            if user.avatar:
                em.set_thumbnail(url=user.display_avatar.url)

            log_message = await logchannel.send(embed=em)
        else:
            log_message = None

        async with self.config.guild(guild).all() as data:
            data["ticket_num"] += 1
            if uid not in data["opened"]:
                data["opened"][uid] = {}
            data["opened"][uid][str(channel_or_thread.id)] = {
                "opened": now.isoformat(),
                "pfp": str(user.display_avatar.url) if user.avatar else None,
                "logmsg": log_message.id if log_message else None,
                "answers": answers,
                "has_response": True if answers else False,
                "message_id": msg.id,
            }

            new_id = await update_active_overview(guild, data)
            if new_id:
                data["overview_msg"] = new_id

        txt = f"Ticket has been created!\nChannel mention: {channel_or_thread.mention}"

        return txt
