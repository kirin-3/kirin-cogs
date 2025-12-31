import asyncio
import logging
import re
from collections import defaultdict
from contextlib import suppress
from datetime import datetime
from typing import List, Optional, Tuple, Union

import discord
from discord.utils import escape_markdown
from redbot.core import Config, commands
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import pagify, text_to_file
from redbot.core.utils.mod import is_admin_or_superior

log = logging.getLogger("red.vrt.tickets.base")


async def can_close(
    bot: Red,
    guild: discord.Guild,
    channel: Union[discord.TextChannel, discord.Thread],
    author: discord.Member,
    owner_id: int,
    conf: dict,
):
    if str(owner_id) not in conf["opened"]:
        return False
    if str(channel.id) not in conf["opened"][str(owner_id)]:
        return False

    # Simplified structure: no panel roles anymore
    user_roles = [r.id for r in author.roles]
    support_roles = [i[0] for i in conf["support_roles"]]

    can_close = False
    if any(i in support_roles for i in user_roles):
        can_close = True
    elif author.id == guild.owner_id:
        can_close = True
    elif await is_admin_or_superior(bot, author):
        can_close = True
    elif str(owner_id) == str(author.id) and conf["user_can_close"]:
        can_close = True
    return can_close


async def ticket_owner_hastyped(channel: discord.TextChannel, user: discord.Member) -> bool:
    async for msg in channel.history(limit=50, oldest_first=True):
        if msg.author.id == user.id:
            return True
    return False


def get_ticket_owner(opened: dict, channel_id: str) -> Optional[str]:
    for uid, tickets in opened.items():
        if channel_id in tickets:
            return uid


async def close_ticket(
    bot: Red,
    member: Union[discord.Member, discord.User],
    guild: discord.Guild,
    channel: Union[discord.TextChannel, discord.Thread],
    conf: dict,
    reason: str | None,
    closedby: str,
    config: Config,
    status: str | None = None,
) -> None:
    opened = conf["opened"]
    if not opened:
        return
    uid = str(member.id)
    cid = str(channel.id)
    if uid not in opened:
        return
    if cid not in opened[uid]:
        return

    ticket = opened[uid][cid]
    pfp = ticket["pfp"]
    
    if not channel.permissions_for(guild.me).manage_channels and isinstance(channel, discord.TextChannel):
        await channel.send("I am missing the `Manage Channels` permission to close this ticket!")
        return
    if not channel.permissions_for(guild.me).manage_threads and isinstance(channel, discord.Thread):
        await channel.send("I am missing the `Manage Threads` permission to close this ticket!")
        return

    opened = int(datetime.fromisoformat(ticket["opened"]).timestamp())
    closed = int(datetime.now().timestamp())
    closer_name = escape_markdown(closedby)

    color = discord.Color.green()
    if status == "Not Verified":
        color = discord.Color.red()

    ticket_num = re.search(r"\d+", channel.name)
    title = f"Ticket Closed #{ticket_num.group()}" if ticket_num else "Ticket Closed"

    embed = discord.Embed(
        title=title,
        color=color,
    )
    embed.add_field(name="Created by", value=f"{member.display_name} ({member.name})", inline=True)
    embed.add_field(name="User ID", value=str(member.id), inline=True)
    embed.add_field(name="Opened on", value=f"<t:{opened}:F>", inline=True)
    embed.add_field(name="Closed on", value=f"<t:{closed}:F>", inline=True)
    embed.add_field(name="Closed by", value=closer_name, inline=True)
    embed.add_field(name="Reason", value=str(reason), inline=False)
    embed.set_thumbnail(url=pfp)

    # Using conf instead of panel since it's flattened
    log_chan: discord.TextChannel = guild.get_channel(conf["log_channel"]) if conf["log_channel"] else None
    
    if log_chan and ticket["logmsg"]:
        try:
            await log_chan.send(embed=embed)
        except discord.HTTPException as e:
            log.warning(f"Failed to send log message: {e}")

        # Delete old log msg
        log_msg_id = ticket["logmsg"]
        try:
            old_log_msg = await log_chan.fetch_message(log_msg_id)
            if old_log_msg:
                await old_log_msg.delete()
        except discord.HTTPException:
            pass

    if conf["dm"]:
        try:
            if status == "Verified":
                await member.send("You are now Verified.")
            elif status == "Not Verified":
                await member.send("You were not verified.")
            else:
                await member.send(embed=embed)
        except discord.Forbidden:
            pass

    # Delete/close ticket channel
    try:
        await channel.delete()
    except discord.DiscordServerError:
        await asyncio.sleep(3)
        try:
            await channel.delete()
        except Exception as e:
            log.error("Failed to delete ticket channel", exc_info=e)

    async with config.guild(guild).all() as conf:
        tickets = conf["opened"]
        if uid not in tickets:
            return
        if cid not in tickets[uid]:
            return
        del tickets[uid][cid]
        # If user has no more tickets, clean up their key from the config
        if not tickets[uid]:
            del tickets[uid]

        new_id = await update_active_overview(guild, conf)
        if new_id:
            conf["overview_msg"] = new_id


async def prune_invalid_tickets(
    guild: discord.Guild,
    conf: dict,
    config: Config,
    ctx: Optional[commands.Context] = None,
) -> bool:
    opened_tickets = conf["opened"]
    if not opened_tickets:
        if ctx:
            await ctx.send("There are no tickets stored in the database.")
        return False

    users_to_remove = []
    tickets_to_remove = []
    count = 0
    for user_id, tickets in opened_tickets.items():
        member = guild.get_member(int(user_id))
        if not member:
            count += len(list(tickets.keys()))
            users_to_remove.append(user_id)
            log.info(f"Cleaning up user {user_id}'s tickets for leaving")
            continue

        if not tickets:
            count += 1
            users_to_remove.append(user_id)
            log.info(f"Cleaning member {member} for having no tickets opened")
            continue

        for channel_id, ticket in tickets.items():
            if guild.get_channel_or_thread(int(channel_id)):
                continue

            count += 1
            log.info(f"Ticket channel {channel_id} no longer exists for {member}")
            tickets_to_remove.append((user_id, channel_id))

            log_message_id = ticket["logmsg"]
            log_channel_id = conf["log_channel"]
            if log_channel_id and log_message_id:
                log_channel = guild.get_channel(log_channel_id)
                try:
                    log_message = await log_channel.fetch_message(log_message_id)
                    await log_message.delete()
                except (discord.NotFound, discord.Forbidden):
                    pass

    if users_to_remove or tickets_to_remove:
        async with config.guild(guild).opened() as opened:
            for uid in users_to_remove:
                del opened[uid]
            for uid, cid in tickets_to_remove:
                if uid not in opened:
                    # User was already removed
                    continue
                if cid not in opened[uid]:
                    # Ticket was already removed
                    continue
                del opened[uid][cid]

    grammar = "ticket" if count == 1 else "tickets"
    if count and ctx:
        txt = "Pruned `{}` invalid {}".format(count, grammar)
        await ctx.send(txt)
    elif not count and ctx:
        await ctx.send("There are no tickets to prune")
    elif count and not ctx:
        log.info(f"{count} {grammar} pruned from {guild.name}")

    return True if count else False


def prep_overview_text(guild: discord.Guild, opened: dict, mention: bool = False) -> str:
    active = []
    for uid, opened_tickets in opened.items():
        member = guild.get_member(int(uid))
        if not member:
            continue
        for ticket_channel_id, ticket_info in opened_tickets.items():
            channel = guild.get_channel_or_thread(int(ticket_channel_id))
            if not channel:
                continue

            open_time_obj = datetime.fromisoformat(ticket_info["opened"])

            entry = [
                channel.mention if mention else channel.name,
                int(open_time_obj.timestamp()),
                member.name,
            ]
            active.append(entry)

    if not active:
        return "There are no active tickets."

    sorted_active = sorted(active, key=lambda x: x[1])

    desc = ""
    for index, i in enumerate(sorted_active):
        chan_mention, ts, username = i
        desc += f"{index + 1}. {chan_mention} <t:{ts}:R> - {username}\n"
    return desc


async def update_active_overview(guild: discord.Guild, conf: dict) -> Optional[int]:
    """Update active ticket overview

    Args:
        guild (discord.Guild): discord server
        conf (dict): settings for the guild

    Returns:
        int: Message ID of the overview panel
    """
    if not conf["overview_channel"]:
        return
    channel: discord.TextChannel = guild.get_channel(conf["overview_channel"])
    if not channel:
        return
    if not channel.permissions_for(guild.me).send_messages:
        return

    txt = prep_overview_text(guild, conf["opened"], conf.get("overview_mention", False))
    title = "Ticket Overview"
    embeds = []
    attachments = []
    if len(txt) < 4000:
        embed = discord.Embed(
            title=title,
            description=txt,
            color=discord.Color.greyple(),
            timestamp=datetime.now(),
        )
        embeds.append(embed)
    elif len(txt) < 5500:
        for p in pagify(txt, page_length=3900):
            embed = discord.Embed(
                title=title,
                description=p,
                color=discord.Color.greyple(),
                timestamp=datetime.now(),
            )
            embeds.append(embed)
    else:
        embed = discord.Embed(
            title=title,
            description="Too many active tickets to include in message!",
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
        embeds.append(embed)
        filename = "Active Tickets.txt"
        file = text_to_file(txt, filename=filename)
        attachments = [file]

    message = None
    if msg_id := conf["overview_msg"]:
        try:
            message = await channel.fetch_message(msg_id)
        except (discord.NotFound, discord.HTTPException):
            pass

    if message:
        try:
            await message.edit(content=None, embeds=embeds, attachments=attachments)
        except discord.Forbidden:
            message = await channel.send(embeds=embeds, files=attachments)
            return message.id
    else:
        try:
            message = await channel.send(embeds=embeds, files=attachments)
            return message.id
        except discord.Forbidden:
            message = await channel.send("Failed to send overview message due to missing permissions")
