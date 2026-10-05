"""The posted shop on a real Red bot: sections, posting, the buy menu, and the post following shop changes."""

from typing import cast

import discord
import pytest
import simcord
from redbot.core.bot import Red

from unicornia.tests.test_simcord_unicornia import red_cogs  # noqa: F401  (the fixture)
from unicornia.unicornia import Unicornia

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 100


def _cog(env: simcord.Env) -> Unicornia:
    cog = cast(Red, env.bot).get_cog("Unicornia")
    assert isinstance(cog, Unicornia)
    return cog


def _components(message: discord.Message) -> list[object]:
    found: list[object] = []
    stack: list[object] = list(message.components)
    while stack:
        component = stack.pop(0)
        found.append(component)
        stack.extend(getattr(component, "children", None) or [])
    return found


def _texts(message: discord.Message) -> str:
    return "\n".join(c.content for c in _components(message) if isinstance(c, discord.components.TextDisplay))


def _options(message: discord.Message) -> list[discord.SelectOption]:
    return next((c.options for c in _components(message) if isinstance(c, discord.SelectMenu)), [])


def _latest(channel: simcord.ChannelHandle, message_id: int) -> discord.Message:
    return next(m for m in channel.history() if m.id == message_id)


async def _world(red_env: simcord.Env) -> tuple[simcord.GuildHandle, simcord.MemberActor, simcord.ChannelHandle]:
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    channel = guild.create_text_channel("shop")
    await red_env.settle()
    return guild, owner, channel


@pytest.mark.asyncio
async def test_staff_post_the_shop_and_members_buy_from_it(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild, owner, channel = await _world(red_env)
    rich = guild.add_member(red_env.create_user("rich"))
    poor = guild.add_member(red_env.create_user("poor"))
    pink, vip = guild.create_role("Pink"), guild.create_role("VIP")
    await red_env.settle()
    bot_guild = cast(discord.Guild, red_env.bot.get_guild(guild.id))
    editor = owner.member
    assert editor is not None

    colors = await cog.shop_section_create(bot_guild, "Color roles", "Type the buy command or use the menu.")
    special = await cog.shop_section_create(bot_guild, "Special roles", "*You do not get these roles' colors.*")
    pink_id = await cog.shop_item_add(
        bot_guild, editor, "Pink", 14_000, cast(discord.Role, bot_guild.get_role(pink.id)), None, colors
    )
    await cog.shop_item_add(bot_guild, editor, "VIP", 0, cast(discord.Role, bot_guild.get_role(vip.id)), None, special)
    await cog.shop_section_banner(bot_guild, colors, PNG)
    await cog.shop_post(bot_guild, cast(discord.TextChannel, bot_guild.get_channel(channel.id)))

    sections = await cog.shop_sections(bot_guild)
    color_post = _latest(channel, cast(int, sections[colors]["message_id"]))
    special_post = _latest(channel, cast(int, sections[special]["message_id"]))
    assert color_post.id < special_post.id  # in section order
    assert f"<@&{pink.id}> ➥ **14,000**" in _texts(color_post) and "`!shop buy 1`" in _texts(color_post)
    assert "Color roles" in _texts(color_post) and [a.filename for a in color_post.attachments] == ["banner.png"]
    assert f"<@&{vip.id}> ➥ Free" in _texts(special_post) and "*You do not get" in _texts(special_post)
    assert [(o.label, o.value, o.description) for o in _options(color_post)] == [("Pink", "1", "14,000 Slut points")]

    await cog.add_balance(rich.id, 20_000)
    offered = await rich.select(color_post, ["1"], custom_id=f"unicornia:shopbuy:{colors}")
    assert offered.response is not None and offered.response.ephemeral
    assert f"Buy <@&{pink.id}> for 14,000" in offered.response.content and "You have 20,000" in offered.response.content
    bought = await rich.click(offered.response, label="Buy")
    assert bought.response is None or "You bought" in bought.response.content
    assert pink.id in {r.id for r in cast(discord.Member, rich.member).roles}
    assert await cog.get_balance(rich.id) == (6_000, 0)

    offered = await poor.select(color_post, ["1"], custom_id=f"unicornia:shopbuy:{colors}")
    assert offered.response is not None
    await poor.click(offered.response, label="Buy")
    assert pink.id not in {r.id for r in cast(discord.Member, poor.member).roles}
    offered = await poor.select(color_post, ["1"], custom_id=f"unicornia:shopbuy:{colors}")
    assert offered.response is not None
    await poor.click(offered.response, label="Cancel")

    # The shop commands keep the post up to date, and `req none` clears a requirement again.
    await owner.send(channel, "!shop edit 1 price 9000")
    assert "**9,000**" in _texts(_latest(channel, color_post.id))
    await owner.send(channel, f"!shop edit 1 req {vip.id}")
    assert f"needs <@&{vip.id}>" in _texts(_latest(channel, color_post.id))
    await owner.send(channel, "!shop edit 1 req none")
    assert "Role requirement removed." in (channel.last_message.content if channel.last_message else "")
    assert "needs" not in _texts(_latest(channel, color_post.id))
    await owner.send(channel, "!shop remove 1")
    assert "Nothing for sale here yet." in _texts(_latest(channel, color_post.id))
    assert not _options(_latest(channel, color_post.id))
    assert pink_id not in {item["id"] for item in (await cog.shop_overview(bot_guild, editor))["items"]}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_sections_change_in_place_and_reposting_replaces_the_shop(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild, owner, channel = await _world(red_env)
    other = guild.create_text_channel("other")
    mod = guild.create_role("Mod", permissions=discord.Permissions(kick_members=True))
    blue = guild.create_role("Blue")
    await red_env.settle()
    bot_guild = cast(discord.Guild, red_env.bot.get_guild(guild.id))
    editor = owner.member
    assert editor is not None
    shop_channel = cast(discord.TextChannel, bot_guild.get_channel(channel.id))

    with pytest.raises(ValueError, match="Create a section"):
        await cog.shop_post(bot_guild, shop_channel)
    first = await cog.shop_section_create(bot_guild, "Colors")
    with pytest.raises(ValueError, match="already a section called colors"):
        await cog.shop_section_create(bot_guild, "colors")
    with pytest.raises(ValueError, match="moderator permissions"):
        await cog.shop_item_add(
            bot_guild, editor, "Mod", 1, cast(discord.Role, bot_guild.get_role(mod.id)), None, first
        )
    blue_id = await cog.shop_item_add(
        bot_guild, editor, "Blue", 5, cast(discord.Role, bot_guild.get_role(blue.id)), None, None
    )
    await cog.shop_post(bot_guild, shop_channel)
    [posted] = [m for m in channel.history() if m.author.id == cast(discord.ClientUser, red_env.bot.user).id]
    assert "Nothing for sale here yet." in _texts(posted)

    await cog.shop_item_edit(bot_guild, editor, blue_id, "Sky blue", 7, None, None, first)
    assert "<@&" in _texts(_latest(channel, posted.id)) and [
        o.label for o in _options(_latest(channel, posted.id))
    ] == ["Sky blue"]
    await cog.shop_section_edit(bot_guild, first, "Colour roles", "Pretty")
    assert "## Colour roles\nPretty" in _texts(_latest(channel, posted.id))

    # A section created after posting goes up at the end.
    second = await cog.shop_section_create(bot_guild, "Extras")
    sections = await cog.shop_sections(bot_guild)
    assert cast(int, sections[second]["message_id"]) > posted.id

    # Reposting elsewhere moves the whole shop; deleting a section deletes its message.
    await cog.shop_post(bot_guild, cast(discord.TextChannel, bot_guild.get_channel(other.id)))
    assert not [m for m in channel.history() if m.author.id == cast(discord.ClientUser, red_env.bot.user).id]
    await cog.shop_section_delete(bot_guild, second)
    assert [s["name"] for s in (await cog.shop_overview(bot_guild, editor))["sections"]] == ["Colour roles"]
    assert len([m for m in other.history() if m.components]) == 1
    with pytest.raises(LookupError):
        await cog.shop_section_edit(bot_guild, second, "Gone", "")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_sections_and_items_reorder_in_place(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild, owner, channel = await _world(red_env)
    red, green = guild.create_role("Red"), guild.create_role("Green")
    await red_env.settle()
    bot_guild = cast(discord.Guild, red_env.bot.get_guild(guild.id))
    editor = owner.member
    assert editor is not None

    colors = await cog.shop_section_create(bot_guild, "Colors")
    extras = await cog.shop_section_create(bot_guild, "Extras")
    red_id = await cog.shop_item_add(
        bot_guild, editor, "Red", 1, cast(discord.Role, bot_guild.get_role(red.id)), None, colors
    )
    green_id = await cog.shop_item_add(
        bot_guild, editor, "Green", 2, cast(discord.Role, bot_guild.get_role(green.id)), None, colors
    )
    await cog.shop_post(bot_guild, cast(discord.TextChannel, bot_guild.get_channel(channel.id)))
    sections = await cog.shop_sections(bot_guild)
    top, bottom = cast(int, sections[colors]["message_id"]), cast(int, sections[extras]["message_id"])

    await cog.shop_item_move(bot_guild, colors, green_id, -1)
    assert [o.label for o in _options(_latest(channel, top))] == ["Green", "Red"]
    await cog.shop_item_move(bot_guild, colors, green_id, -1)  # already first: nothing happens
    assert [o.label for o in _options(_latest(channel, top))] == ["Green", "Red"]
    with pytest.raises(LookupError):
        await cog.shop_item_move(bot_guild, extras, red_id, 1)

    # Moving Extras up swaps the two messages' contents, so the channel's order changes without a new post.
    await cog.shop_section_move(bot_guild, extras, -1)
    assert "## Extras" in _texts(_latest(channel, top)) and "## Colors" in _texts(_latest(channel, bottom))
    assert [o.label for o in _options(_latest(channel, bottom))] == ["Green", "Red"]
    sections = await cog.shop_sections(bot_guild)
    assert list(sections) == [extras, colors] and sections[extras]["message_id"] == top
    await cog.shop_section_move(bot_guild, extras, -1)  # already first
    assert list(await cog.shop_sections(bot_guild)) == [extras, colors]
    assert [s["name"] for s in (await cog.shop_overview(bot_guild, editor))["sections"]] == ["Extras", "Colors"]

    # Reposting keeps the new order, and the menu still buys from the moved section.
    await cog.shop_post(bot_guild, cast(discord.TextChannel, bot_guild.get_channel(channel.id)))
    posted = [m for m in channel.history() if m.components]
    assert ["## Extras" in _texts(posted[0]), "## Colors" in _texts(posted[1])] == [True, True]
    simcord.assert_no_errors(red_env)
