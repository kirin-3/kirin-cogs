"""Tickets on a real Red instance driven through SimCord."""

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
    logs: simcord.ChannelHandle | None = None
    staff: simcord.MemberActor | None = None


def _tickets_cog(env: simcord.Env) -> Tickets:
    cog = cast(Red, env.bot).get_cog("Tickets")
    assert isinstance(cog, Tickets)
    return cog


async def _setup_panel(env: simcord.Env, *, logs: bool = False, support: bool = False) -> Panel:
    """Configure a ticket panel through the admin commands, the way a server admin would."""
    bot = cast(Red, env.bot)
    guild = env.create_guild()
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(env.create_user("admin"), roles=[admin_role])
    member = guild.add_member(env.create_user("member"))
    category = guild.create_category("Tickets")
    channel = guild.create_text_channel("support")
    log_channel = guild.create_text_channel("ticket-logs") if logs else None
    staff: simcord.MemberActor | None = None
    if support:
        support_role = guild.create_role("Support")
        staff = guild.add_member(env.create_user("staff"), roles=[support_role])
    await env.settle()

    # Red's admin_or_permissions check rejects a plain member. Pop the expected error so
    # simcord.assert_no_errors at the end of each test still catches anything else.
    await member.send(channel, f"!tickets category {category.id}")
    assert isinstance(env.errors.pop(), commands.CheckFailure)

    text_channel = bot.get_channel(channel.id)
    assert isinstance(text_channel, discord.TextChannel)
    message = await text_channel.send("Need help? Open a ticket.")
    await admin.send(channel, f"!tickets category {category.id}")
    # Deterministic channel names so the close logs say "Ticket Closed #1".
    await admin.send(channel, "!tickets ticketname ticket-{num}")
    await admin.send(channel, f"!tickets panelmessage {message.id}")
    if log_channel is not None:
        await admin.send(channel, f"!tickets logchannel {log_channel.mention}")
    if staff is not None:
        await admin.send(channel, "!tickets supportrole Support true")
    return Panel(bot, _tickets_cog(env), guild, admin, member, channel, message, log_channel, staff)


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


async def _welcome_message(channel: discord.TextChannel, bot: Red) -> discord.Message:
    """The bot's first message in a fresh ticket: the welcome embed carrying the Close button."""
    bot_user = bot.user
    assert bot_user is not None
    for message in [m async for m in channel.history()]:
        if message.author.id == bot_user.id and message.components:
            return message
    raise AssertionError("the ticket channel has no welcome message with buttons")


def _bot_replies(handle: simcord.ChannelHandle, bot: Red) -> list[discord.Message]:
    bot_user = bot.user
    assert bot_user is not None
    return [m for m in handle.history() if m.author.id == bot_user.id]


def _log_embeds(panel: Panel) -> list[discord.Embed]:
    assert panel.logs is not None
    return [e for m in _bot_replies(panel.logs, panel.bot) for e in m.embeds]


async def _close_with_reason(
    actor: simcord.MemberActor, welcome: discord.Message, reason: str
) -> simcord.InteractionResult:
    """Click the Close button on the welcome message and submit the reason modal."""
    shown = await actor.click(welcome, label="Close")
    assert shown.modal is not None
    field_ids = [item["custom_id"] for row in shown.modal["components"] for item in row["components"]]
    assert len(field_ids) == 1
    return await actor.submit_modal(shown, {field_ids[0]: reason})


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


@pytest.mark.asyncio
async def test_blacklisted_member_is_refused_without_a_modal(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    member_obj = panel.member.member
    assert member_obj is not None
    await panel.admin.send(panel.channel, f"!tickets blacklist {member_obj.mention}")

    result = await panel.member.click(panel.message, label="Open a Ticket")
    assert result.modal is None
    assert result.response is not None
    assert result.response.embeds[0].description == "You been blacklisted from creating tickets!"
    assert await panel.cog.config.guild_from_id(panel.guild.id).opened() == {}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_required_role_gates_the_panel(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    gatekeeper = panel.guild.create_role("Gatekeeper")
    await red_env.settle()
    await panel.admin.send(panel.channel, "!tickets openrole Gatekeeper")

    result = await panel.member.click(panel.message, label="Open a Ticket")
    assert result.modal is None
    assert result.response is not None
    description = result.response.embeds[0].description or ""
    assert description.startswith("You must have one of the following roles to open this ticket:")
    assert gatekeeper.mention in description
    assert await panel.cog.config.guild_from_id(panel.guild.id).opened() == {}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_second_ticket_is_refused_at_the_limit(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    await _open_ticket(panel)  # max_tickets defaults to 1

    result = await panel.member.click(panel.message, label="Open a Ticket")
    assert result.modal is None
    assert result.response is not None
    assert (result.response.embeds[0].description or "").startswith(
        "You have the maximum amount of tickets opened already!"
    )
    opened = await panel.cog.config.guild_from_id(panel.guild.id).opened()
    assert len(opened[str(panel.member.id)]) == 1
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_owner_closes_own_ticket_through_the_button(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env, logs=True)
    channel = await _open_ticket(panel)
    welcome = await _welcome_message(channel, panel.bot)

    # The "Closing..." followup lived in the ticket channel, which close_ticket has since
    # deleted, so it is no longer retrievable; assert on the durable effects instead.
    await _close_with_reason(panel.member, welcome, "done helping")

    assert channel.name not in panel.guild.channels
    assert await panel.cog.config.guild_from_id(panel.guild.id).opened() == {}
    # The close replaced the "Ticket Opened" log entry with a closed one.
    assert [e.title for e in _log_embeds(panel)] == ["Ticket Closed #1"]
    fields = {f.name: f.value or "" for f in _log_embeds(panel)[0].fields}
    assert fields["Closed by"] == "member"
    assert fields["Reason"] == "done helping"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_staff_close_requires_a_verification_status(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env, support=True)
    assert panel.staff is not None
    staff_member = panel.staff.member
    assert staff_member is not None
    channel = await _open_ticket(panel)
    # Support roles get read access to every ticket.
    assert channel.permissions_for(staff_member).view_channel
    welcome = await _welcome_message(channel, panel.bot)

    shown = await panel.staff.click(welcome, label="Close")
    assert shown.response is not None
    assert shown.response.content == "Please select the verification status for this user."

    # The production Verified role doesn't exist in this guild; the ticket must stay open.
    verified = await panel.staff.click(shown.response, label="Verified")
    assert verified.followups[-1].content == "The Verified role is missing. The ticket was left open."
    assert channel.name in panel.guild.channels
    assert await panel.cog.config.guild_from_id(panel.guild.id).opened() != {}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_staff_marks_not_verified_and_ticket_closes(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env, logs=True, support=True)
    assert panel.staff is not None
    channel = await _open_ticket(panel)
    welcome = await _welcome_message(channel, panel.bot)

    shown = await panel.staff.click(welcome, label="Close")
    assert shown.response is not None
    modal = await panel.staff.click(shown.response, label="Not Verified")
    assert modal.modal is not None
    field_ids = [item["custom_id"] for row in modal.modal["components"] for item in row["components"]]
    assert len(field_ids) == 1
    await panel.staff.submit_modal(modal, {field_ids[0]: "photos were blurry"})

    assert channel.name not in panel.guild.channels
    assert await panel.cog.config.guild_from_id(panel.guild.id).opened() == {}
    closed = [e for e in _log_embeds(panel) if e.title == "Ticket Closed #1"]
    assert closed and closed[0].color == discord.Color.red()
    fields = {f.name: f.value or "" for f in closed[0].fields}
    assert fields["Reason"] == "photos were blurry"
    assert fields["Closed by"] == "staff"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_overview_message_tracks_active_tickets(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    overview = panel.guild.create_text_channel("ticket-overview")
    await red_env.settle()
    await panel.admin.send(panel.channel, f"!tickets overview {overview.mention}")

    def overview_description() -> str:
        embeds = [e for m in _bot_replies(overview, panel.bot) for e in m.embeds if e.title == "Ticket Overview"]
        assert len(embeds) == 1
        return embeds[0].description or ""

    assert overview_description() == "There are no active tickets."

    channel = await _open_ticket(panel)
    description = overview_description()
    # overview_mention is off by default, so tickets are listed by channel name.
    assert description.startswith("1. ticket-1 ")
    assert description.rstrip().endswith("- member")

    welcome = await _welcome_message(channel, panel.bot)
    await _close_with_reason(panel.member, welcome, "done")
    assert overview_description() == "There are no active tickets."
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_add_command_gated_by_user_can_manage(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    channel = await _open_ticket(panel)
    ticket = panel.guild.channels[channel.name]
    friend = panel.guild.add_member(red_env.create_user("friend"))
    await red_env.settle()
    friend_obj = friend.member
    assert friend_obj is not None

    await panel.member.send(ticket, f"!add {friend_obj.mention}")
    assert any(
        m.content == "You do not have permissions to add users to this ticket" for m in _bot_replies(ticket, panel.bot)
    )

    await panel.admin.send(panel.channel, "!tickets selfmanage")
    await panel.member.send(ticket, f"!add {friend_obj.mention}")
    assert any(
        m.content == f"**{friend_obj.name}** has been added to this ticket!" for m in _bot_replies(ticket, panel.bot)
    )
    assert channel.permissions_for(friend_obj).view_channel
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_member_leaving_guild_closes_their_ticket(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env, logs=True)
    channel = await _open_ticket(panel)

    panel.guild.remove_member(panel.member)
    await red_env.settle()

    assert channel.name not in panel.guild.channels
    assert await panel.cog.config.guild_from_id(panel.guild.id).opened() == {}
    closed = [e for e in _log_embeds(panel) if e.title == "Ticket Closed #1"]
    assert closed
    fields = {f.name: f.value or "" for f in closed[0].fields}
    assert fields["Reason"] == "User left guild(Auto-Close)"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_deleted_ticket_channel_is_pruned_from_config(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    channel = await _open_ticket(panel)

    # A deletion from outside the cog (say, an admin with another client) must prune the record.
    red_env.backend.delete_channel(channel.id)
    await red_env.settle()

    assert await panel.cog.config.guild_from_id(panel.guild.id).opened() == {}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_delayed_close_is_cancelled_by_a_reply(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    channel = await _open_ticket(panel)
    ticket = panel.guild.channels[channel.name]

    await panel.member.send(ticket, "!close 5m")
    # Let the command get past its 1.5-second grace sleep and park inside wait_for.
    await red_env.advance_time(2)
    await panel.member.send(ticket, "hold on")

    assert any(m.content == "Closing cancelled!" for m in _bot_replies(ticket, panel.bot))
    assert await panel.cog.config.guild_from_id(panel.guild.id).opened() != {}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_remind_instructions_button_posts_the_format(red_env: simcord.Env) -> None:
    panel = await _setup_panel(red_env)
    channel = await _open_ticket(panel)
    welcome = await _welcome_message(channel, panel.bot)

    result = await panel.member.click(welcome, label="Remind Instructions")
    assert result.response is not None
    assert "PLEASE ADHERE TO THE FOLLOWING FORMAT" in (result.response.embeds[0].description or "")
    simcord.assert_no_errors(red_env)
