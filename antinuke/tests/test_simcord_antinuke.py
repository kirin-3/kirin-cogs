"""AntiNuke on a real Red instance driven through SimCord.

Rogue-admin actions reach the cog the way they do in production: as audit log
entries. SimCord only models the bot's own HTTP client, so a member acting
from their own client is simulated by recording the resulting audit entry
directly on the backend (SimCord's omnipotent-setup idiom; builders never
record entries implicitly, exactly like real Discord).
"""

from dataclasses import dataclass
from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from antinuke.antinuke import AntiNuke


@pytest.fixture
def red_cogs() -> list[str]:
    return ["antinuke"]


@dataclass
class Setup:
    bot: Red
    cog: AntiNuke
    guild: simcord.GuildHandle
    owner: simcord.MemberActor
    admin: simcord.MemberActor
    culprit: simcord.MemberActor
    regular: simcord.RoleHandle
    quarantine_role: simcord.RoleHandle
    channel: simcord.ChannelHandle
    logs: simcord.ChannelHandle


def _antinuke_cog(env: simcord.Env) -> AntiNuke:
    cog = cast(Red, env.bot).get_cog("AntiNuke")
    assert isinstance(cog, AntiNuke)
    return cog


async def _setup(env: simcord.Env) -> Setup:
    """A guild with AntiNuke enabled through the owner's commands, the way production sets it up."""
    bot = cast(Red, env.bot)
    # The AntiNuke command group only accepts the guild owner, so make one.
    owner_user = env.create_user("owner")
    guild = env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    regular = guild.create_role("Regular")
    quarantine_role = guild.create_role("Quarantine")
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(env.create_user("admin"), roles=[admin_role])
    culprit = guild.add_member(env.create_user("culprit"), roles=[regular])
    channel = guild.create_text_channel("general")
    logs = guild.create_text_channel("mod-logs")
    await env.settle()

    await owner.send(channel, "!an enable")
    await owner.send(channel, f"!an logchannel {logs.mention}")
    await owner.send(channel, f"!an quarantinerole {quarantine_role.mention}")
    return Setup(bot, _antinuke_cog(env), guild, owner, admin, culprit, regular, quarantine_role, channel, logs)


async def _rogue_action(
    env: simcord.Env,
    guild: simcord.GuildHandle,
    actor: simcord.MemberActor,
    action: discord.AuditLogAction,
    target_id: int | None = None,
) -> None:
    """The actor performs a monitored action from their own client.

    Real Discord always fills ``target_id`` for channel/role-typed actions, and
    discord.py cannot even build ``entry.target`` without one; substitute a
    snowflake when the test does not care about the target.
    """
    if target_id is None:
        target_id = env.backend.snowflake()
    env.backend.record_audit_log(guild.id, action.value, user_id=actor.id, target_id=target_id)
    await env.settle()


def _bot_replies(handle: simcord.ChannelHandle, bot: Red) -> list[discord.Message]:
    bot_user = bot.user
    assert bot_user is not None
    return [m for m in handle.history() if m.author.id == bot_user.id]


def _log_embeds(setup: Setup) -> list[discord.Embed]:
    return [e for m in _bot_replies(setup.logs, setup.bot) for e in m.embeds]


def _everyone_id(guild: simcord.GuildHandle) -> int:
    me = guild.me
    assert me is not None
    return me.guild.default_role.id


def _role_ids(actor: simcord.MemberActor) -> set[int]:
    member = actor.member
    assert member is not None
    return {role.id for role in member.roles}


async def _quarantined(setup: Setup) -> dict:
    return await setup.cog.config.guild_from_id(setup.guild.id).quarantined_users()


@pytest.mark.asyncio
async def test_rogue_admin_crossing_the_threshold_is_quarantined(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)  # channel_delete: threshold 2 / 60s by default

    await _rogue_action(red_env, setup.guild, setup.culprit, discord.AuditLogAction.channel_delete)
    # One deletion is below the threshold: counted, but no action yet.
    assert await _quarantined(setup) == {}
    assert setup.cog.action_cache.get_count(setup.guild.id, setup.culprit.id, "channel_delete", 60) == 1

    await _rogue_action(red_env, setup.guild, setup.culprit, discord.AuditLogAction.channel_delete)
    record = (await _quarantined(setup))[str(setup.culprit.id)]
    assert record["state"] == "completed"
    assert record["trigger_action"] == "channel_delete"
    assert record["reason"] == "AntiNuke triggered: channel_delete"
    # The pre-quarantine roles were snapshotted, then replaced by the quarantine role.
    assert record["roles"] == [setup.regular.id]
    assert _role_ids(setup.culprit) == {_everyone_id(setup.guild), setup.quarantine_role.id}
    # The cache is cleared so a restored user does not immediately re-quarantine.
    assert setup.cog.action_cache.get_count(setup.guild.id, setup.culprit.id, "channel_delete", 60) == 0

    quarantine_logs = [e for e in _log_embeds(setup) if e.title == "🛡️ AntiNuke Quarantine"]
    assert len(quarantine_logs) == 1
    fields = {f.name: f.value or "" for f in quarantine_logs[0].fields}
    assert fields["Trigger"] == "**Channel Deletion**"
    assert fields["Roles Stripped"] == "1"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_guild_prune_triggers_instant_quarantine(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)  # guild_prune: threshold 0 = instant action

    await _rogue_action(red_env, setup.guild, setup.culprit, discord.AuditLogAction.member_prune)

    record = (await _quarantined(setup))[str(setup.culprit.id)]
    assert record["trigger_action"] == "guild_prune"
    assert record["state"] == "completed"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_trusted_users_and_roles_bypass_monitoring(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)  # channel_create: threshold 3 / 60s by default
    trusted_role = setup.guild.create_role("Trusted")
    protected = setup.guild.add_member(red_env.create_user("protected"), roles=[trusted_role])
    await red_env.settle()

    await setup.owner.send(setup.channel, f"!an trust adduser {setup.culprit.mention}")
    await setup.owner.send(setup.channel, f"!an trust addrole {trusted_role.mention}")

    for _ in range(3):
        await _rogue_action(red_env, setup.guild, setup.culprit, discord.AuditLogAction.channel_create)
        await _rogue_action(red_env, setup.guild, protected, discord.AuditLogAction.channel_create)

    assert await _quarantined(setup) == {}
    # Trusted actors are skipped before the cache is touched.
    assert setup.cog.action_cache.get_count(setup.guild.id, setup.culprit.id, "channel_create", 60) == 0
    assert setup.cog.action_cache.get_count(setup.guild.id, protected.id, "channel_create", 60) == 0
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_disabled_guild_ignores_actions(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await setup.owner.send(setup.channel, "!an disable")

    for _ in range(5):
        await _rogue_action(red_env, setup.guild, setup.culprit, discord.AuditLogAction.channel_delete)

    assert await setup.cog.config.guild_from_id(setup.guild.id).enabled() is False
    assert await _quarantined(setup) == {}
    assert _role_ids(setup.culprit) == {_everyone_id(setup.guild), setup.regular.id}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_bot_culprit_is_kicked_instead_of_quarantined(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)  # webhook_create: threshold 2 / 60s by default
    roguebot = setup.guild.add_member(red_env.create_user("roguebot", bot=True))
    await red_env.settle()

    await _rogue_action(red_env, setup.guild, roguebot, discord.AuditLogAction.webhook_create)
    assert roguebot.id in setup.guild.member_ids()

    await _rogue_action(red_env, setup.guild, roguebot, discord.AuditLogAction.webhook_create)
    # Bots keep their managed role, so they are removed instead of quarantined.
    assert roguebot.id not in setup.guild.member_ids()
    assert await _quarantined(setup) == {}
    removal_logs = [e for e in _log_embeds(setup) if e.title == "🛡️ AntiNuke Bot Removed"]
    assert len(removal_logs) == 1
    fields = {f.name: f.value or "" for f in removal_logs[0].fields}
    assert fields["Trigger"] == "**Webhook Creation**"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_bot_add_quarantines_adder_and_kicks_added_bot(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)  # bot_add: threshold 1, auto-kick on by default
    added_bot = setup.guild.add_member(red_env.create_user("addedbot", bot=True))
    await red_env.settle()

    await _rogue_action(red_env, setup.guild, setup.culprit, discord.AuditLogAction.bot_add, target_id=added_bot.id)

    record = (await _quarantined(setup))[str(setup.culprit.id)]
    assert record["trigger_action"] == "bot_add"
    assert added_bot.id not in setup.guild.member_ids()
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_monitor_commands_control_what_counts(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    owner = setup.owner

    await owner.send(setup.channel, "!an monitor enable nonsense")
    assert any("❌ Invalid action type" in m.content for m in _bot_replies(setup.channel, setup.bot))

    await owner.send(setup.channel, "!an monitor disable channel_delete")
    for _ in range(3):
        await _rogue_action(red_env, setup.guild, setup.culprit, discord.AuditLogAction.channel_delete)
    assert await _quarantined(setup) == {}

    await owner.send(setup.channel, "!an monitor enable channel_delete")
    await owner.send(setup.channel, "!an monitor threshold channel_delete 1 30")
    assert any(
        "**Channel Deletion** threshold set to 1 actions within 30 seconds" in m.content
        for m in _bot_replies(setup.channel, setup.bot)
    )
    await _rogue_action(red_env, setup.guild, setup.culprit, discord.AuditLogAction.channel_delete)
    assert str(setup.culprit.id) in await _quarantined(setup)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_force_and_restore_roundtrip(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    await setup.owner.send(setup.channel, f"!an quarantine force {setup.culprit.mention} testing")
    assert any(
        f"✅ {setup.culprit.mention} has been quarantined." in m.content for m in _bot_replies(setup.channel, setup.bot)
    )
    assert _role_ids(setup.culprit) == {_everyone_id(setup.guild), setup.quarantine_role.id}

    await setup.owner.send(setup.channel, f"!an quarantine restore {setup.culprit.mention}")
    assert any(
        f"✅ {setup.culprit.mention} has been restored." in m.content for m in _bot_replies(setup.channel, setup.bot)
    )
    assert _role_ids(setup.culprit) == {_everyone_id(setup.guild), setup.regular.id}
    assert await _quarantined(setup) == {}
    assert any(e.title == "✅ AntiNuke Restoration" for e in _log_embeds(setup))
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_hierarchy_refusal_leaves_user_alone_and_alerts_the_log(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    bot_member = setup.guild.me
    assert bot_member is not None
    # A role above the bot's top role: quarantine is impossible for this member.
    untouchable_role = setup.guild.create_role("Untouchable", position=bot_member.top_role.position + 5)
    untouchable = setup.guild.add_member(red_env.create_user("untouchable"), roles=[untouchable_role])
    await red_env.settle()

    await setup.owner.send(setup.channel, f"!an quarantine force {untouchable.mention}")
    assert any(
        "❌ Cannot quarantine" in m.content and "equal or higher roles" in m.content
        for m in _bot_replies(setup.channel, setup.bot)
    )

    # The listener path hits the same guard and reports it to the log channel.
    for _ in range(3):
        await _rogue_action(red_env, setup.guild, untouchable, discord.AuditLogAction.channel_delete)
    assert await _quarantined(setup) == {}
    hierarchy_logs = [e for e in _log_embeds(setup) if e.title == "⚠️ AntiNuke Hierarchy Issue"]
    assert hierarchy_logs, "expected a hierarchy-issue alert in the log channel"
    assert untouchable.id in setup.guild.member_ids()
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_antinuke_commands_are_owner_only(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)

    # Even a Discord administrator is not the settings authority.
    await setup.admin.send(setup.channel, "!an settings")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)

    await setup.owner.send(setup.channel, "!an settings")
    assert any(m.content.startswith("## AntiNuke Settings") for m in _bot_replies(setup.channel, setup.bot))
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_quarantine_list_info_and_cleanup(red_env: simcord.Env) -> None:
    setup = await _setup(red_env)
    await setup.owner.send(setup.channel, f"!an quarantine force {setup.culprit.mention} testing")

    await setup.owner.send(setup.channel, "!an quarantine list")
    assert any(
        "Quarantined Users" in m.content and setup.culprit.mention in m.content
        for m in _bot_replies(setup.channel, setup.bot)
    )

    await setup.owner.send(setup.channel, f"!an quarantine info {setup.culprit.mention}")
    assert any(
        e.title == f"🛡️ Quarantine Info: {setup.culprit.name}"
        for m in _bot_replies(setup.channel, setup.bot)
        for e in m.embeds
    )

    setup.guild.remove_member(setup.culprit)
    await red_env.settle()
    await setup.owner.send(setup.channel, "!an quarantine cleanup")
    assert any("✅ Cleaned up 1 quarantine record(s)" in m.content for m in _bot_replies(setup.channel, setup.bot))
    assert await _quarantined(setup) == {}
    simcord.assert_no_errors(red_env)
