"""Honeypot on a real Red instance driven through SimCord.

The cog only acts in Unicornia's guild, honeypot channel and log channel, and
exempts a hardcoded staff role, so the suite reproduces those exact IDs: the
guild through ``create_guild(id=...)``, and the channels and staff role by
registering models with pinned IDs on the backend and announcing them (SimCord
snowflakes every ID its creation APIs hand out). The cog reads account tenure
from ``datetime.now(UTC)`` against ``Member.joined_at``, which SimCord stamps
from its virtual clock (2026-01-01) — freshly added members therefore count as
long-tenured and take the quarantine path, while the ban path needs a member
whose cached ``joined_at`` is moved to two days before the real clock.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red
from simcord.actors import MemberActor
from simcord.backend import serializers
from simcord.backend.models.channel import Channel
from simcord.backend.models.role import Role

from honeypot.honeypot import (
    BAN_NOTICE,
    ENFORCEMENT_REASON,
    GUILD_ID,
    HONEYPOT_CHANNEL_ID,
    LOG_CHANNEL_ID,
    QUARANTINE_NOTICE,
    STAFF_ROLE_ID,
    Honeypot,
)

RECENT_JOIN = (datetime.now(UTC) - timedelta(days=2)).isoformat()


@pytest.fixture
def red_cogs() -> list[str]:
    return ["honeypot"]


@dataclass
class Setup:
    bot: Red
    cog: Honeypot
    guild: simcord.GuildHandle
    owner: MemberActor
    staff: MemberActor
    veteran: MemberActor
    regular: simcord.RoleHandle
    honeypot_channel: simcord.ChannelHandle
    logs: simcord.ChannelHandle
    room: simcord.ChannelHandle


def _pin_channel(env: simcord.Env, guild: simcord.GuildHandle, name: str, channel_id: int) -> simcord.ChannelHandle:
    """Create a channel under a pinned ID the way the API cannot (see module docstring)."""
    backend = env.backend
    channel = backend.create_channel(guild.id, name, announce=False)
    guild_model = backend.get_guild(guild.id)
    guild_model.channel_ids.remove(channel.id)
    del backend.channels[channel.id]
    backend.messages.pop(channel.id, None)
    channel.id = channel_id
    backend.channels[channel_id] = channel
    backend.messages[channel_id] = {}
    guild_model.channel_ids.append(channel_id)
    backend.emit("CHANNEL_CREATE", serializers.channel_payload(backend, channel))
    return simcord.ChannelHandle(env, guild, cast(Channel, channel))


def _pin_role(env: simcord.Env, guild: simcord.GuildHandle, name: str, role_id: int) -> simcord.RoleHandle:
    backend = env.backend
    role = Role(id=role_id, name=name, position=1)
    backend.get_guild(guild.id).roles[role_id] = role
    backend.emit("GUILD_ROLE_CREATE", {"guild_id": str(guild.id), "role": serializers.role_payload(role)})
    return simcord.RoleHandle(env, guild, role)


def _add_member(
    env: simcord.Env,
    guild: simcord.GuildHandle,
    user: simcord.UserHandle,
    *,
    roles: tuple[simcord.RoleHandle, ...] = (),
    joined_at: str | None = None,
) -> MemberActor:
    """Add a member whose cached join date the cog will believe (see module docstring)."""
    backend = env.backend
    backend.add_member(guild.id, user.id, roles=[r.id for r in roles], announce=False)
    guild_model = backend.get_guild(guild.id)
    member = guild_model.members[user.id]
    if joined_at is not None:
        member.joined_at = joined_at
    payload = dict(serializers.member_payload(backend, guild_model, member))
    payload["guild_id"] = str(guild.id)
    backend.emit("GUILD_MEMBER_ADD", payload)
    return MemberActor(env, guild, user)


def _honeypot_cog(env: simcord.Env) -> Honeypot:
    cog = cast(Red, env.bot).get_cog("Honeypot")
    assert isinstance(cog, Honeypot)
    return cog


async def _setup(env: simcord.Env) -> Setup:
    owner_user = env.create_user("owner")
    guild = env.create_guild("Unicornia", id=GUILD_ID, owner=owner_user)
    owner = guild.add_member(owner_user)
    _pin_role(env, guild, "Staff", STAFF_ROLE_ID)
    honeypot_channel = _pin_channel(env, guild, "honeypot", HONEYPOT_CHANNEL_ID)
    logs = _pin_channel(env, guild, "mod-logs", LOG_CHANNEL_ID)
    room = guild.create_text_channel("staff-room")
    regular = guild.create_role("Regular")
    staff = _add_member(env, guild, env.create_user("staff"))
    env.backend.add_member_role(guild.id, staff.id, STAFF_ROLE_ID)
    veteran = _add_member(env, guild, env.create_user("veteran"), roles=(regular,))
    await env.settle()
    return Setup(
        cast(Red, env.bot), _honeypot_cog(env), guild, owner, staff, veteran, regular, honeypot_channel, logs, room
    )


def _member(actor: MemberActor) -> discord.Member:
    member = actor.member
    assert member is not None
    return member


def _role_ids(actor: MemberActor) -> set[int]:
    return {role.id for role in _member(actor).roles}


def _bot_replies(handle: simcord.ChannelHandle, bot: Red) -> list[discord.Message]:
    bot_user = bot.user
    assert bot_user is not None
    return [m for m in handle.history() if m.author.id == bot_user.id]


def _log_embeds(setup: Setup, *, title: str | None = None) -> list[discord.Embed]:
    return [e for m in _bot_replies(setup.logs, setup.bot) for e in m.embeds if title is None or e.title == title]


def _dm_contents(env: simcord.Env, actor: MemberActor) -> list[str]:
    backend = env.backend
    channels = [c for c in backend.channels.values() if actor.id in c.recipient_ids]
    return [m.content for c in channels for m in backend.messages[c.id].values()]


async def _records(setup: Setup) -> dict:
    return await setup.cog.config.guild_from_id(GUILD_ID).quarantined_users()


@pytest.mark.asyncio
async def test_established_member_posting_is_quarantined(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    message = await setup.veteran.send(setup.honeypot_channel, "free nitro click here")
    await red_env.settle()

    assert not any(m.id == message.id for m in setup.honeypot_channel.history())
    veteran = _member(setup.veteran)
    assert _role_ids(setup.veteran) == {veteran.guild.default_role.id}  # assignable roles stripped
    assert veteran.timed_out_until is not None
    record = (await _records(setup))[str(setup.veteran.id)]
    assert record["state"] == "completed"
    assert record["roles"] == [setup.regular.id]
    assert QUARANTINE_NOTICE in _dm_contents(red_env, setup.veteran)

    embed = _log_embeds(setup, title="Honeypot quarantine")[-1]
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Member"] == f"veteran ({setup.veteran.id})"
    assert fields["Roles stripped"] == "1"
    assert fields["DM delivered"] == "True"
    assert fields["Message content"] == "free nitro click here"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_new_account_posting_is_banned(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    newbie = _add_member(red_env, setup.guild, red_env.create_user("newbie"), joined_at=RECENT_JOIN)
    await red_env.settle()

    await newbie.send(setup.honeypot_channel, "spam", attachments=[("invoice.pdf", b"pdf bytes")])
    await red_env.settle()

    assert setup.guild.get_ban(newbie) == {"user": newbie, "reason": ENFORCEMENT_REASON}
    assert newbie.id not in setup.guild.member_ids()
    assert str(newbie.id) not in await _records(setup)
    assert BAN_NOTICE in _dm_contents(red_env, newbie)

    embed = _log_embeds(setup, title="Honeypot ban")[-1]
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Tenure"] == "2.00 days"
    assert fields["DM delivered"] == "True"
    assert fields["Attachments"] == "invoice.pdf"
    assert fields["Message content"] == "spam"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_staff_bots_and_webhooks_are_ignored(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    evilbot = setup.guild.add_member(red_env.create_user("evilbot", bot=True))
    webhook = setup.guild.create_webhook(setup.honeypot_channel, "hook")
    await red_env.settle()

    staff_message = await setup.staff.send(setup.honeypot_channel, "staff checking the trap")
    bot_message = await evilbot.send(setup.honeypot_channel, "beep")
    await webhook.send("hook post")
    await red_env.settle()

    kept = {m.id for m in setup.honeypot_channel.history()}
    assert {staff_message.id, bot_message.id} <= kept  # webhook send returns no discord.Message
    assert len(kept) == 3
    assert await _records(setup) == {}
    assert not _log_embeds(setup)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_other_channels_and_guilds_are_ignored(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    elsewhere = setup.guild.create_text_channel("general")
    other_guild = red_env.create_guild("Elsewhere")
    other_honeypot = other_guild.create_text_channel("honeypot")
    other_veteran = other_guild.add_member(red_env.create_user("other"))
    await red_env.settle()

    message = await setup.veteran.send(elsewhere, "not the honeypot")
    other_message = await other_veteran.send(other_honeypot, "wrong guild")
    await red_env.settle()

    assert any(m.id == message.id for m in elsewhere.history())
    assert any(m.id == other_message.id for m in other_honeypot.history())
    assert await _records(setup) == {}
    assert not _log_embeds(setup)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_owner_trigger_alerts_without_targeting(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.owner.send(setup.honeypot_channel, "oops")
    await red_env.settle()

    assert not setup.honeypot_channel.history()  # the trigger is still deleted
    assert setup.owner.id in setup.guild.member_ids()
    assert await _records(setup) == {}
    embed = _log_embeds(setup, title="Honeypot owner alert")[-1]
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Attempted action"] == "enforcement"
    assert fields["Details"] == "The guild owner triggered the honeypot and was not targeted."
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_second_post_from_a_contained_member_only_deletes(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await setup.veteran.send(setup.honeypot_channel, "first")
    await red_env.settle()
    first_record = (await _records(setup))[str(setup.veteran.id)]
    first_timeout = _member(setup.veteran).timed_out_until

    second = await setup.veteran.send(setup.honeypot_channel, "second")
    await red_env.settle()

    assert not any(m.id == second.id for m in setup.honeypot_channel.history())
    assert (await _records(setup))[str(setup.veteran.id)] == first_record  # nothing rewritten
    assert _member(setup.veteran).timed_out_until == first_timeout  # timeout not extended
    assert len(_log_embeds(setup, title="Honeypot quarantine")) == 1
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_rejoined_contained_member_is_guarded_not_banned(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await setup.veteran.send(setup.honeypot_channel, "first")
    await red_env.settle()
    record = (await _records(setup))[str(setup.veteran.id)]

    # They leave and rejoin with a fresh 2-day-old account age: still contained by the record.
    setup.guild.remove_member(setup.veteran)
    await red_env.settle()
    veteran_user = red_env.backend.users[setup.veteran.id]
    rejoined = _add_member(red_env, setup.guild, simcord.UserHandle(red_env, veteran_user), joined_at=RECENT_JOIN)
    await red_env.settle()
    message = await rejoined.send(setup.honeypot_channel, "again")
    await red_env.settle()

    assert not any(m.id == message.id for m in setup.honeypot_channel.history())
    assert setup.guild.get_ban(rejoined) is None  # the completed record held the ban path back
    assert rejoined.id in setup.guild.member_ids()
    assert (await _records(setup))[str(setup.veteran.id)] == record
    assert len(_log_embeds(setup, title="Honeypot quarantine")) == 1
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_manual_role_release_lets_a_repeat_post_requarantine(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await setup.veteran.send(setup.honeypot_channel, "first")
    await red_env.settle()

    # Staff give the roles back by hand, which releases the enforced marker.
    red_env.backend.add_member_role(setup.guild.id, setup.veteran.id, setup.regular.id)
    await red_env.settle()
    assert setup.regular.id in _role_ids(setup.veteran)

    await setup.veteran.send(setup.honeypot_channel, "again")
    await red_env.settle()

    assert _role_ids(setup.veteran) == {_member(setup.veteran).guild.default_role.id}  # stripped again
    record = (await _records(setup))[str(setup.veteran.id)]
    assert record["state"] == "completed"
    assert record["roles"] == [setup.regular.id]  # the earlier snapshot was preserved and extended
    embeds = _log_embeds(setup, title="Honeypot quarantine")
    assert len(embeds) == 2
    repeat_fields = {f.name: f.value for f in embeds[-1].fields}
    assert "Repeat quarantine" in repeat_fields
    assert len(_dm_contents(red_env, setup.veteran)) == 2  # both notices went out
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_restore_returns_roles_clears_timeout_and_record(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await setup.veteran.send(setup.honeypot_channel, "first")
    await red_env.settle()

    await setup.staff.send(setup.room, f"!honeypot restore {setup.veteran.mention}")
    await red_env.settle()

    assert any(
        f"Restored {setup.veteran.mention}; 0 role(s) could not be reapplied." in m.content
        for m in _bot_replies(setup.room, setup.bot)
    )
    assert _role_ids(setup.veteran) == {_member(setup.veteran).guild.default_role.id, setup.regular.id}
    assert _member(setup.veteran).timed_out_until is None
    assert await _records(setup) == {}
    embed = _log_embeds(setup, title="Honeypot restore")[-1]
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Restored by"] == f"staff ({setup.staff.id})"
    assert fields["Unrestorable roles"] == "0"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_restore_for_a_departed_user_keeps_the_record(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await setup.veteran.send(setup.honeypot_channel, "first")
    await red_env.settle()
    setup.guild.remove_member(setup.veteran)
    await red_env.settle()

    await setup.staff.send(setup.room, f"!honeypot restore {setup.veteran.id}")
    await red_env.settle()

    assert any("is no longer in the server" in m.content for m in _bot_replies(setup.room, setup.bot))
    assert str(setup.veteran.id) in await _records(setup)  # kept in case they rejoin
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_clear_drops_the_record_but_keeps_the_containment(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await setup.veteran.send(setup.honeypot_channel, "first")
    await red_env.settle()

    await setup.staff.send(setup.room, f"!honeypot clear {setup.veteran.mention}")
    await red_env.settle()

    assert any(
        f"Cleared {setup.veteran.mention}'s quarantine record" in m.content for m in _bot_replies(setup.room, setup.bot)
    )
    assert await _records(setup) == {}
    assert _role_ids(setup.veteran) == {_member(setup.veteran).guild.default_role.id}  # still contained
    assert _member(setup.veteran).timed_out_until is not None
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_hierarchy_refusal_marks_failed_and_alerts(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    bot_member = setup.guild.me
    assert bot_member is not None
    untouchable = setup.guild.create_role("Untouchable", position=bot_member.top_role.position + 5)
    target = _add_member(red_env, setup.guild, red_env.create_user("target"), roles=(untouchable, setup.regular))
    await red_env.settle()
    before = _role_ids(target)

    message = await target.send(setup.honeypot_channel, "above the law")
    await red_env.settle()

    assert not any(m.id == message.id for m in setup.honeypot_channel.history())
    assert _role_ids(target) == before  # the quarantine could not touch them
    record = (await _records(setup))[str(target.id)]
    assert record["state"] == "failed"
    assert record["roles"] == [setup.regular.id]
    embed = _log_embeds(setup, title="Honeypot hierarchy alert")[-1]
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Attempted action"] == "quarantine"
    assert "above the bot in the hierarchy" in (fields["Details"] or "")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_list_reports_records_and_the_gate_blocks_plain_members(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    plain = setup.guild.add_member(red_env.create_user("plain"))
    await red_env.settle()

    await plain.send(setup.room, "!honeypot list")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)

    await setup.staff.send(setup.room, "!honeypot list")
    assert any("There are no honeypot quarantine records." in m.content for m in _bot_replies(setup.room, setup.bot))

    await setup.veteran.send(setup.honeypot_channel, "first")
    await red_env.settle()
    await setup.staff.send(setup.room, "!honeypot list")
    await red_env.settle()
    record = (await _records(setup))[str(setup.veteran.id)]
    assert any(
        f"- {setup.veteran.mention} — {record['state']}, {record['quarantined_at']}, 1 stored role(s)" in m.content
        for m in _bot_replies(setup.room, setup.bot)
    )
    simcord.assert_no_errors(red_env)
