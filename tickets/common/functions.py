import asyncio
import logging
from datetime import datetime
from io import StringIO

import discord
from redbot.core import commands
from redbot.core.utils.chat_formatting import pagify

from ..abc import MixinMeta
from ..common.utils import update_active_overview
from ..common.views import CloseView

log = logging.getLogger("red.vrt.tickets.functions")


class Functions(MixinMeta):
    @commands.Cog.listener()
    async def on_assistant_cog_add(self, cog: commands.Cog):
        schema = {
            "name": "get_ticket_info",
            "description": (
                "Fetch support ticket requirements available for the user to open (Use this before opening a ticket). "
                "The user MUST answer the questions in detail before the ticket can be opened!"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        }
        await cog.register_function("Tickets", schema)

        schema = {
            "name": "create_ticket_for_user",
            "description": (
                "Create a support ticket for the user you are speaking with if you are unable to help sufficiently. "
                "Use `get_ticket_info` function before this one to get response section requirements. "
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer1": {
                        "type": "string",
                        "description": "The answer to the first question if one exists.",
                    },
                    "answer2": {
                        "type": "string",
                        "description": "The answer to the second question if one exists.",
                    },
                    "answer3": {
                        "type": "string",
                        "description": "The answer to the third question if one exists.",
                    },
                    "answer4": {
                        "type": "string",
                        "description": "The answer to the fourth question if one exists.",
                    },
                    "answer5": {
                        "type": "string",
                        "description": "The answer to the fifth question if one exists.",
                    },
                },
                "required": [],
            },
        }
        await cog.register_function("Tickets", schema)

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
        answer1: str = None,
        answer2: str = None,
        answer3: str = None,
        answer4: str = None,
        answer5: str = None,
        *args,
        **kwargs,
    ) -> str:
        """Create a ticket for the given member.

        Args:
            user (discord.Member): User to open a ticket for.
            answer1 (str, optional): The answer to the first ticket question. Defaults to None.
            answer2 (str, optional): The answer to the second ticket question. Defaults to None.
            answer3 (str, optional): The answer to the third ticket question. Defaults to None.
            answer4 (str, optional): The answer to the fourth ticket question. Defaults to None.
            answer5 (str, optional): The answer to the fifth ticket question. Defaults to None.
        """

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

        # Prepare the modal responses
        responses = [
            answer1,
            answer2,
            answer3,
            answer4,
            answer5,
        ]
        answers = {}
        if modal := conf.get("modal"):
            for idx, i in enumerate(list(modal.values())):
                if i.get("required") and not responses[idx]:
                    return f"THE FOLLOWING TICKET QUESTION WAS NOT ANSWERED!\n{i['label']}"
                response = str(responses[idx])
                if "DISCOVERABLE" in guild.features:
                    response = response.replace("Discord", "").replace("discord", "")

                answers[i["label"]] = response

        form_embed = discord.Embed()
        if answers:
            title = "Submission Info"
            form_embed = discord.Embed(color=user.color)
            if user.avatar:
                form_embed.set_author(name=title, icon_url=user.display_avatar.url)
            else:
                form_embed.set_author(name=title)

            for question, answer in answers.items():
                if len(answer) <= 1024:
                    form_embed.add_field(name=question, value=answer, inline=False)
                    continue

                chunks = [ans for ans in pagify(answer, page_length=1024)]
                for index, chunk in enumerate(chunks):
                    form_embed.add_field(
                        name=f"{question} ({index + 1})",
                        value=chunk,
                        inline=False,
                    )

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

        if len(form_embed.fields) > 0:
            form_msg = await channel_or_thread.send(embed=form_embed)
            try:
                asyncio.create_task(form_msg.pin(reason="Ticket form questions"))
            except discord.Forbidden:
                txt = "I tried to pin the response message but don't have the manage messages permissions!"
                asyncio.create_task(channel_or_thread.send(txt))

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

            for question, answer in answers.items():
                em.add_field(name=f"__{question}__", value=answer, inline=False)

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
