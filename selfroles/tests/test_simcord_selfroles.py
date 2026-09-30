"""Self-role menus on a real Red bot: building a menu, posting it, picking and clearing roles, and the role checks."""

from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from selfroles.selfroles import SelfRoles

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 100


@pytest.fixture
def red_cogs() -> list[str]:
    return ["selfroles"]


def _cog(red_env: simcord.Env) -> SelfRoles:
    cog = cast(Red, red_env.bot).get_cog("SelfRoles")
    assert isinstance(cog, SelfRoles)
    return cog


def _role_ids(actor: simcord.MemberActor) -> set[int]:
    assert actor.member is not None
    return {role.id for role in actor.member.roles}


def _texts(message: discord.Message) -> str:
    return "\n".join(str(component) for component in message.components)


@pytest.mark.asyncio
async def test_admin_builds_and_posts_a_menu_and_members_pick_and_clear(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    member = guild.add_member(red_env.create_user("member"))
    straight, bi, gay = guild.create_role("Straight"), guild.create_role("Bisexual"), guild.create_role("Gay")
    channel = guild.create_text_channel("roles")
    await red_env.settle()

    await member.send(channel, "!selfroles create 2 Orientation")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    await owner.send(channel, "!selfroles create 2 Orientation")
    await owner.send(channel, f"!selfroles addrole orientation {straight.id} ❤️")
    await owner.send(channel, f"!selfroles addrole Orientation {bi.id} 🤍")
    await owner.send(channel, f"!selfroles addrole Orientation {gay.id}")
    await owner.send(channel, "!selfroles banner Orientation", attachments=[("orientation.png", PNG)])
    await owner.send(channel, "!selfroles post Orientation")

    [(category_id, category)] = (await cog.categories(cast(discord.Guild, red_env.bot.get_guild(guild.id)))).items()
    assert [entry["emoji"] for entry in category["roles"]] == ["❤️", "🤍", ""]
    assert category["banner"] == "png"
    menu = channel.last_message
    assert menu is not None and menu.id == category["message_id"]
    assert "Orientation" in _texts(menu) and "Pick up to 2." in _texts(menu) and f"<@&{bi.id}>" in _texts(menu)
    assert [a.filename for a in menu.attachments] == ["banner.png"]
    sends = [
        r for r in red_env.http_requests if r.method == "POST" and r.path.endswith(f"/channels/{channel.id}/messages")
    ]
    assert sends and all((r.json or {}).get("allowed_mentions") == {"parse": []} for r in sends[-1:])

    picked = await member.select(menu, [str(straight.id), str(bi.id)], custom_id=f"selfroles:pick:{category_id}")
    assert picked.followups and picked.followups[0].ephemeral
    assert _role_ids(member) >= {straight.id, bi.id} and gay.id not in _role_ids(member)

    await member.select(menu, [str(gay.id)], custom_id=f"selfroles:pick:{category_id}")
    assert gay.id in _role_ids(member) and not _role_ids(member) & {straight.id, bi.id}

    cleared = await member.click(menu, label="Clear")
    assert "Removed your Orientation roles." in cleared.followups[0].content
    assert not _role_ids(member) & {straight.id, bi.id, gay.id}

    await owner.send(channel, f"!selfroles removerole Orientation {gay.id}")
    menu_now = next(m for m in channel.history() if m.id == menu.id)
    assert f"<@&{gay.id}>" not in _texts(menu_now) and f"<@&{bi.id}>" in _texts(menu_now)
    assert [a.filename for a in menu_now.attachments] == ["banner.png"]

    await owner.send(channel, "!selfroles create 1 Other")
    await owner.send(channel, f"!selfroles addrole Other {bi.id}")
    reply = channel.last_message
    assert reply is not None and reply.content == "Bisexual is already in Orientation."

    bot_guild = cast(discord.Guild, red_env.bot.get_guild(guild.id))
    await owner.send(channel, "!selfroles banner Orientation", attachments=[("new.gif", b"GIF89a" + b"\0" * 50)])
    assert not cog.banner_path(bot_guild, category_id, "png").exists()
    assert cog.banner_path(bot_guild, category_id, "gif").exists()
    menu_now = next(m for m in channel.history() if m.id == menu.id)
    assert [a.filename for a in menu_now.attachments] == ["banner.gif"]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_a_change_discord_refuses_is_rolled_back(red_env: simcord.Env, monkeypatch: pytest.MonkeyPatch) -> None:
    cog = _cog(red_env)
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    taken, single = guild.create_role("Taken"), guild.create_role("Single")
    channel = guild.create_text_channel("roles")
    await red_env.settle()
    await owner.send(channel, "!selfroles create 1 Relation")
    await owner.send(channel, f"!selfroles addrole Relation {taken.id}")
    await owner.send(channel, "!selfroles post Relation")

    class _Refused:
        status, reason = 400, "Bad Request"

    async def refuse(*_: object) -> None:
        raise discord.HTTPException(_Refused(), {"message": "Invalid emoji"})  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(cog, "_refresh", refuse)
    await owner.send(channel, f"!selfroles addrole Relation {single.id} 💔")

    reply = channel.last_message
    assert (
        reply is not None
        and "Discord refused the updated menu, so nothing was changed (Invalid emoji)" in reply.content
    )
    bot_guild = cast(discord.Guild, red_env.bot.get_guild(guild.id))
    [category] = (await cog.categories(bot_guild)).values()
    assert [entry["id"] for entry in category["roles"]] == [taken.id]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_roles_with_moderator_permissions_are_refused_and_stop_being_handed_out(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    member = guild.add_member(red_env.create_user("member"))
    mod = guild.create_role("Mod", permissions=discord.Permissions(kick_members=True))
    single = guild.create_role("Single")
    channel = guild.create_text_channel("roles")
    await red_env.settle()

    await owner.send(channel, "!selfroles create 1 Relation")
    await owner.send(channel, f"!selfroles addrole Relation {mod.id}")
    reply = channel.last_message
    assert reply is not None and "moderator permissions (kick members)" in reply.content
    await owner.send(channel, f"!selfroles addrole Relation {single.id}")
    await owner.send(channel, "!selfroles post Relation")
    menu = channel.last_message
    assert menu is not None
    bot_guild = cast(discord.Guild, red_env.bot.get_guild(guild.id))
    [category_id] = await cog.categories(bot_guild)
    assert [entry["id"] for entry in (await cog.categories(bot_guild))[category_id]["roles"]] == [single.id]
    assert owner.member is not None
    [shown] = await cog.overview(bot_guild, owner.member)
    assert not {choice["id"] for choice in shown["choices"]} & {mod.id, single.id, guild.id}
    assert shown["channel"] == "#roles" and shown["url"].endswith(f"/{channel.id}/{menu.id}")
    assert shown["roles"] == [{"id": single.id, "name": "Single", "emoji": "", "problem": None}]

    await cast(discord.Role, bot_guild.get_role(single.id)).edit(permissions=discord.Permissions(ban_members=True))
    await red_env.settle()
    await member.select(menu, [str(single.id)], custom_id=f"selfroles:pick:{category_id}")
    assert single.id not in _role_ids(member)
    [shown] = await cog.overview(bot_guild, owner.member)
    assert shown["roles"][0]["problem"] == "Single has moderator permissions (ban members)."
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_staff_can_only_add_roles_below_their_own_top_role(red_env: simcord.Env) -> None:
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    above = guild.create_role("Above")
    helper_role = guild.create_role("Helper", permissions=discord.Permissions(manage_roles=True))
    helper = guild.add_member(red_env.create_user("helper"), roles=[helper_role])
    channel = guild.create_text_channel("roles")
    await red_env.settle()
    bot_guild = cast(discord.Guild, red_env.bot.get_guild(guild.id))
    assert cast(discord.Role, bot_guild.get_role(above.id)) > cast(discord.Role, bot_guild.get_role(helper_role.id))

    await owner.send(channel, "!selfroles create 1 Titles")
    await helper.send(channel, f"!selfroles addrole Titles {above.id}")
    reply = channel.last_message
    assert reply is not None and "not below your top role" in reply.content
    assert helper.member is not None
    [shown] = await _cog(red_env).overview(bot_guild, helper.member)
    assert above.id not in {choice["id"] for choice in shown["choices"]}
    await helper.send(channel, "!selfroles create 1 Other")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)  # creating is for admins
    simcord.assert_no_errors(red_env)
