import logging
from datetime import datetime
from io import StringIO

import discord

from ..abc import MixinMeta
from ..common.constants import TicketState
from ..common.utils import update_active_overview

log = logging.getLogger("red.kirin_cogs.tickets.functions")


class Functions(MixinMeta):
    # @commands.Cog.listener()
    # async def on_assistant_cog_add(self, cog: commands.Cog):
    #     pass

    async def _finalize_ticket_creation(
        self,
        guild: discord.Guild,
        uid: str,
        pending_key: str,
        channel_id: int,
        ticket: dict,
    ) -> None:
        """Promote a pending ticket while retaining the full guild config shape."""
        async with self.config.guild(guild).all() as data:
            opened_data = data.setdefault("opened", {})
            user_tickets = opened_data.setdefault(uid, {})
            user_tickets.pop(pending_key, None)
            user_tickets[str(channel_id)] = ticket

            new_id = await update_active_overview(guild, data)
            if new_id:
                data["overview_msg"] = new_id

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

        if (modal := conf.get("modal")) and (questions := list(modal.values())):
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

        logchannel_raw = guild.get_channel(conf["log_channel"]) if conf["log_channel"] else None
        logchannel = logchannel_raw if isinstance(logchannel_raw, discord.TextChannel) else None
        category = guild.get_channel(conf["category_id"]) if conf["category_id"] else None
        channel = guild.get_channel(conf["channel_id"]) if conf["channel_id"] else None

        if not isinstance(category, discord.CategoryChannel):
            return "The category for this panel is missing!"
        if not channel:
            return "The channel required for this ticket panel is missing!"

        # Serialize reservations for this member while allowing different members
        # to create tickets concurrently.
        async with self._creation_lock(guild.id, user.id):  # pyright: ignore[reportAttributeAccessIssue]
            # Re-read config under lock to get accurate state
            conf = await self.config.guild(guild).all()

            # Check if the member has already reached the maximum number of open tickets allowed
            max_tickets = conf["max_tickets"]
            opened = conf["opened"]
            uid = str(user.id)
            # Pending tickets reserve a slot so overlapping requests cannot
            # both pass the limit while Discord channel creation is in flight.
            if uid in opened:
                active_count = len(opened[uid])
                if max_tickets <= active_count:
                    return "This user has reached the maximum number of open tickets allowed!"

            # Verify that the member has the required roles to open a ticket from the specified panel
            required_roles = conf.get("required_roles", [])
            if required_roles and not any(role.id in required_roles for role in user.roles):
                return "This user does not have the required roles to open this ticket."

            # Allocate ticket_num under lock
            async with self._num_lock(guild.id):  # pyright: ignore[reportAttributeAccessIssue]
                num = (await self.config.guild(guild).ticket_num()) or 1
                await self.config.guild(guild).ticket_num.set(num + 1)

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
            reconcile_token = f"kirin-ticket:{guild.id}:{user.id}:{num}"

            # 7.3: Persist PENDING record BEFORE Discord channel effect
            pending_key = f"pending-{num}"
            async with self.config.guild(guild).opened() as opened_data:
                if uid not in opened_data:
                    opened_data[uid] = {}
                opened_data[uid][pending_key] = {
                    "opened": now.isoformat(),
                    "pfp": str(user.display_avatar.url) if user.avatar else None,
                    "logmsg": None,
                    "answers": {},
                    "has_response": False,
                    "message_id": 0,
                    "channel_id": None,
                    "reconcile_token": reconcile_token,
                    "state": TicketState.PENDING,
                }

        # Now create the Discord channel (outside creation lock for shorter hold time)
        answers: dict = {}
        discord.Embed()

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

        default_channel_name = f"ticket-{num}"
        try:
            try:
                channel_or_thread: discord.TextChannel = await category.create_text_channel(
                    channel_name, overwrites=overwrite, topic=reconcile_token
                )
            except Exception as e:
                if "Contains words not allowed" in str(e):
                    channel_or_thread = await category.create_text_channel(
                        default_channel_name, overwrites=overwrite, topic=reconcile_token
                    )
                    await channel_or_thread.send(
                        f"I was not able to name the ticket properly due to Discord's filter!\nIntended name: {channel_name}"
                    )
                else:
                    raise e
        except discord.Forbidden:
            # Clean up the pending record
            async with self.config.guild(guild).opened() as opened_data:
                if uid in opened_data and pending_key in opened_data[uid]:
                    del opened_data[uid][pending_key]
                    if not opened_data[uid]:
                        del opened_data[uid]
            return "Missing requried permissions to create the ticket!"

        except Exception as e:
            log.error("Error creating ticket channel", exc_info=e)
            # Clean up the pending record
            async with self.config.guild(guild).opened() as opened_data:
                if uid in opened_data and pending_key in opened_data[uid]:
                    del opened_data[uid][pending_key]
                    if not opened_data[uid]:
                        del opened_data[uid]
            return f"ERROR: {e}"

        # Persist the Discord side effect immediately. If later message/log writes
        # fail or the process exits, startup reconciliation can recover this channel.
        async with self.config.guild(guild).opened() as opened_data:
            pending = opened_data.get(uid, {}).get(pending_key)
            if pending is not None:
                pending["channel_id"] = channel_or_thread.id

        prefix = (await self.bot.get_valid_prefixes(guild))[0]
        default_message = "Welcome to your ticket channel " + f"{user.display_name}!"
        user_can_close = conf["user_can_close"]
        if user_can_close:
            default_message += f"\nYou or an admin can close this with the `{prefix}close` command"

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
                embed_color = (
                    discord.Color(color_val) if color_val is not None and isinstance(color_val, int) else user.color
                )
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

        # 7.3: Promote PENDING -> ACTIVE with final channel ID as the key
        await self._finalize_ticket_creation(
            guild,
            uid,
            pending_key,
            channel_or_thread.id,
            {
                "opened": now.isoformat(),
                "pfp": str(user.display_avatar.url) if user.avatar else None,
                "logmsg": log_message.id if log_message else None,
                "answers": answers,
                "has_response": bool(answers),
                "message_id": msg.id,
                "state": TicketState.ACTIVE,
            },
        )

        txt = f"Ticket has been created!\nChannel mention: {channel_or_thread.mention}"

        return txt
