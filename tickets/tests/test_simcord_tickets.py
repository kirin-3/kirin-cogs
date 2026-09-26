"""Pilot: tickets on a real Red instance driven through SimCord."""

from dataclasses import dataclass
from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from tickets.tickets import Tickets


@pytest.fixture
def red_cogs() -> list[str]:
    return ["tickets"]


@dataclass
class Panel:
    bot: Red
    cog: Tickets
    guild: simcord.GuildHandle
    admin: simcord.MemberActor
    member: simcord.MemberActor
    channel: simcord.ChannelHandle
    message: discord.Message


def _tickets_cog(env: simcord.Env) -> Tickets:
    cog = cast(Red, env.bot).get_cog("Tickets")
    assert isinstance(cog, Tickets)
    return cog


async def _setup_panel(env: simcord.Env) -> Panel:
    """Configure a ticket panel through the admin commands, the way a server admin would."""
    bot = cast(Red, env.bot)
    guild = env.create_guild()
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(env.create_user("admin"), roles=[admin_role])
    member = guild.add_member(env.create_user("member"))
    category = guild.create_category("Tickets")
    channel = guild.create_text_channel("support")
    await env.settle()

    # Red's admin_or_permissions check rejects a plain member. Pop the expected error so
    # simcord.assert_no_errors at the end of each test still catches anything else.
    await member.send(channel, f"!tickets category {category.id}")
    assert isinstance(env.errors.pop(), commands.CheckFailure)

    text_channel = bot.get_channel(channel.id)
    assert isinstance(text_channel, discord.TextChannel)
    message = await text_channel.send("Need help? Open a ticket.")
    await admin.send(channel, f"!tickets category {category.id}")
    await admin.send(channel, f"!tickets panelmessage {message.id}")
    return Panel(bot, _tickets_cog(env), guild, admin, member, channel, message)


async def _open_ticket(panel: Panel) -> discord.TextChannel:
    """The member clicks the panel button and submits the verification modal."""
    shown = await panel.member.click(panel.message, label="Open a Ticket")
    assert shown.modal is not None

    done = await panel.member.submit_modal(shown, {"verification_image": ("id.png", b"fake png bytes")})
    assert done.followups[-1].ephemeral
    assert done.followups[-1].content.startswith("Ticket has been created!")

    opened = await panel.cog.config.guild_from_id(panel.guild.id).opened()
    tickets = opened[str(panel.member.id)]
    assert len(tickets) == 1
    channel = panel.bot.get_channel(int(next(iter(tickets))))
    assert isinstance(channel, discord.TextChannel)
    return channel


@pytest.mark.asyncio
async def test_member_opens_ticket_through_panel_and_verification_modal(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    channel = await _open_ticket(panel)

    assert channel.category is not None and channel.category.name == "Tickets"
    assert panel.member.member is not None and channel.permissions_for(panel.member.member).view_channel
    posted = [m async for m in channel.history()]
    assert any(e.title == "Verification Image 1" for m in posted for e in m.embeds)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_suspended_panel_refuses_without_opening_modal(red_env: simcord.Env) -> None:
    # Each test gets its own Red data dir; nothing leaks from the test above.
    assert await _tickets_cog(red_env).config.all_guilds() == {}

    panel = await _setup_panel(red_env)
    await panel.admin.send(panel.channel, "!tickets suspend Back soon")

    result = await panel.member.click(panel.message, label="Open a Ticket")
    assert result.modal is None
    assert result.ephemeral
    assert result.response is not None and result.response.embeds[0].description == "Back soon"
    assert await panel.cog.config.guild_from_id(panel.guild.id).opened() == {}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_renameticket_slash_command_respects_ticket_permissions(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    channel = await _open_ticket(panel)
    ticket = panel.guild.channels[channel.name]

    # Slash commands only exist once the bot owner enables and syncs them, as in production.
    panel.bot.owner_ids.add(panel.admin.id)  # what Red's --owner flag does
    await panel.admin.send(panel.channel, "!slash enable renameticket")
    await panel.admin.send(panel.channel, "!slash sync")

    # Ticket openers can't rename unless user_can_rename is on (off by default).
    denied = await panel.member.slash(ticket, "renameticket", new_name="renamed")
    assert denied.response is not None
    assert denied.response.content == "You do not have permissions to rename this ticket"
    assert channel.name == ticket.name

    # The Red owner counts as admin_or_superior.
    renamed = await panel.admin.slash(ticket, "renameticket", new_name="verified-member")
    assert renamed.response is not None
    assert renamed.response.content == "Renaming channel to **verified-member**"
    assert channel.name == "verified-member"
    simcord.assert_no_errors(red_env)
