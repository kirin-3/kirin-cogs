import importlib
from collections import Counter
from collections.abc import Iterator
from datetime import date, timedelta
from typing import cast
from unittest.mock import AsyncMock, patch

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from responder.main import ResponderCog
from responder.responders.base_rate_responder import daily_roll, rating_bar
from responder.responders.rate_dimbo import DimboRate
from responder.responders.rate_dom import DomRate
from responder.responders.rate_stinky import StinkyRate

GIF = "https://media.tenor.com/abc/potato.gif"


@pytest.fixture
def red_cogs() -> list[str]:
    return ["responder"]


@pytest.fixture
def tenor() -> Iterator[AsyncMock]:
    with patch("responder.unicornia.web.get_tenor_gifs", new=AsyncMock(return_value=[GIF])) as mock:
        yield mock


def _world(red_env: simcord.Env) -> tuple[simcord.GuildHandle, simcord.ChannelHandle, simcord.ChannelHandle]:
    """A guild with one channel the cog answers in and one it ignores."""
    guild = red_env.create_guild()
    allowed = guild.create_text_channel("bot-commands")
    other = guild.create_text_channel("general")
    const = importlib.import_module("responder.const")
    const.SERVER_PERMISSIONS[guild.id] = {"name": "Test", "allowed_channels": {allowed.id: "bot-commands"}}
    return guild, allowed, other


def _bot_messages(red_env: simcord.Env, channel: simcord.ChannelHandle) -> list[discord.Message]:
    bot_id = cast(Red, red_env.bot).user.id  # pyright: ignore[reportOptionalMemberAccess]
    return [m for m in channel.history() if m.author.id == bot_id]


@pytest.mark.asyncio
async def test_rate_only_answers_in_allowed_channels(red_env: simcord.Env) -> None:
    guild, allowed, other = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(other, "cute rate")
    assert _bot_messages(red_env, other) == []

    await member.send(allowed, "cute rate")
    [reply] = _bot_messages(red_env, allowed)
    embed = reply.embeds[0]
    assert embed.title == "❯ Cute Rate"
    assert embed.description is not None and "member" in embed.description
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_rate_anything_is_for_supporters_and_uses_tenor(red_env: simcord.Env, tenor: AsyncMock) -> None:
    guild, allowed, _ = _world(red_env)
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(allowed, "potato rate")
    assert _bot_messages(red_env, allowed) == []
    tenor.assert_not_awaited()

    await admin.send(allowed, f"potato rate <@{member.id}>")
    [reply] = _bot_messages(red_env, allowed)
    embed = reply.embeds[0]
    assert embed.title == "❯ Potato Rate"
    assert embed.description is not None and embed.description.startswith("member is ")
    assert embed.thumbnail.url == GIF
    tenor.assert_awaited_once_with("potato")
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_rate_anything_falls_back_to_avatar_when_tenor_fails(red_env: simcord.Env, tenor: AsyncMock) -> None:
    tenor.side_effect = TimeoutError
    guild, allowed, _ = _world(red_env)
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    await red_env.settle()

    await admin.send(allowed, "potato rate")
    [reply] = _bot_messages(red_env, allowed)
    assert reply.embeds[0].thumbnail.url not in (None, GIF)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_the_game_has_a_silent_cooldown(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(allowed, "I lost The Game")
    await member.send(allowed, "The Game again")
    assert [m.content for m in _bot_messages(red_env, allowed)] == ["I just lost The Game."]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_unknown_target_gets_a_reply(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(allowed, "cute rate 123456789012345678")
    [reply] = _bot_messages(red_env, allowed)
    assert reply.content == 'Unable to find a member using "123456789012345678".'
    simcord.assert_no_errors(red_env)


def _responder(red_env: simcord.Env) -> ResponderCog:
    cog = cast(Red, red_env.bot).get_cog("ResponderCog")
    assert isinstance(cog, ResponderCog)
    return cog


@pytest.mark.asyncio
async def test_daddy_opt_out_command_stops_and_restores_replies(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()
    cog = _responder(red_env)

    with patch("responder.responders.daddy.random.randint", return_value=0):
        await member.send(allowed, "I'm tired")
        await member.send(allowed, "!daddyoptout")
        await member.send(allowed, "I'm still tired")

    replies = [m.content for m in _bot_messages(red_env, allowed)]
    assert replies[0] == "Hi, tired! I'm your daddy..."
    assert replies[1].startswith("You won't get daddy replies anymore.")
    assert len(replies) == 2
    assert await cog.config.user_from_id(member.id).daddy() is False

    await member.send(allowed, "!daddyoptout")
    assert _bot_messages(red_env, allowed)[-1].content.startswith("Daddy replies are back on for you.")
    assert await cog.config.all_users() == {}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_daddy_opt_out_slash_command_is_ephemeral(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, allowed, _ = _world(red_env)
    owner = guild.add_member(red_env.create_user("owner"))
    await red_env.settle()
    cast(set[int], bot.owner_ids).add(owner.id)  # what Red's --owner flag does
    await owner.send(allowed, "!slash enable daddyoptout")
    await owner.send(allowed, "!slash sync")

    result = await owner.slash(allowed, "daddyoptout")

    simcord.assert_responded(result, ephemeral=True)
    assert await _responder(red_env).config.user_from_id(owner.id).daddy() is False
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_settings_api_and_data_deletion(red_env: simcord.Env) -> None:
    cog = _responder(red_env)

    assert (await cog.settings_for(1))["daddy"]["value"] is True
    await cog.set_toggle(1, "daddy", False)
    assert (await cog.settings_for(1))["daddy"]["value"] is False
    with pytest.raises(ValueError):
        await cog.set_toggle(1, "nope", False)

    await cog.red_delete_data_for_user(requester="user", user_id=1)
    assert await cog.config.all_users() == {}


@pytest.mark.asyncio
async def test_kirin_opt_outs_stay_on_their_own_responders(red_env: simcord.Env) -> None:
    const = importlib.import_module("responder.const")
    ignores_kirin = {type(r).__name__: const.KIRIN_ID in r.never_respond for r in _responder(red_env).responders}
    assert ignores_kirin["LongCatResponder"] and ignores_kirin["TableUnflipResponder"]
    assert not ignores_kirin["ImDaddyResponder"] and not ignores_kirin["TheGameResponder"]
    assert const.KIRIN_ID not in const.NEVER_RESPOND


@pytest.mark.asyncio
async def test_rate_anything_keeps_its_topic_while_tenor_answers(red_env: simcord.Env, tenor: AsyncMock) -> None:
    guild, allowed, _ = _world(red_env)
    admin_role = guild.create_role("Admin", permissions=discord.Permissions(administrator=True))
    admin = guild.add_member(red_env.create_user("admin"), roles=[admin_role])
    await red_env.settle()
    rate = next(r for r in _responder(red_env).responders if type(r).__name__ == "RateResponder")
    default = rate.rate_classes["default"]

    async def another_message_arrives(term: str) -> list[str]:
        default.topic = "carrot"  # a second "carrot rate" dispatched during the Tenor request
        return [GIF]

    tenor.side_effect = another_message_arrives
    await admin.send(allowed, "potato rate")
    [reply] = _bot_messages(red_env, allowed)
    assert reply.embeds[0].title == "❯ Potato Rate"
    assert reply.embeds[0].description is not None
    assert reply.embeds[0].description.splitlines()[0].endswith("% potato")
    simcord.assert_no_errors(red_env)


def test_daily_roll_is_stable_for_a_day_and_changes_across_days() -> None:
    today = date(2026, 9, 29)
    assert daily_roll(1, "gay", today) == daily_roll(1, "gay", today)
    rolls = [daily_roll(1, "gay", today + timedelta(days=n)) for n in range(30)]
    assert len(set(rolls)) > 5 and all(0 <= roll <= 100 for roll in rolls)


def test_rating_bar_clamps_and_cycles_its_emojis() -> None:
    assert rating_bar(0, ("🟫",), "⬛") == "⬛" * 10
    assert rating_bar(100, ("🟫",), "⬛") == "🟫" * 10
    assert rating_bar(690, ("🟫",), "⬛") == "🟫" * 10
    assert rating_bar(-20, ("🟫",), "⬛") == "⬛" * 10
    assert rating_bar(74, ("🟥", "🟧", "🟨"), "⬛") == "🟥🟧🟨🟥🟧🟨🟥⬛⬛⬛"


def _last_embed(red_env: simcord.Env, channel: simcord.ChannelHandle) -> discord.Embed:
    return _bot_messages(red_env, channel)[-1].embeds[0]


@pytest.mark.asyncio
async def test_a_rate_replies_with_a_topic_bar_and_stays_the_same_all_day(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    asked = await member.send(allowed, "stinky rate")
    await member.send(allowed, "Stinky rate")

    first, second = _bot_messages(red_env, allowed)
    rating = daily_roll(member.id, "stinky")
    expected = f"member is {rating}% stinky\n\n{rating_bar(rating, ('🟫',), '⬛')}  **{rating}%**"
    assert first.embeds[0].description == second.embeds[0].description == expected
    assert first.embeds[0].color == discord.Color(StinkyRate.color)
    assert first.embeds[0].footer.text is None
    assert first.reference is not None and first.reference.message_id == asked.id
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_member_overrides_set_the_rating_and_colour(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    stinkiest = {"description": "{target} is the stinkiest.", "rating": 100}
    with patch.dict(StinkyRate.user_overrides, {member.id: stinkiest}):
        await member.send(allowed, "stinky rate")
    assert _last_embed(red_env, allowed).description == f"member is the stinkiest.\n\n{'🟫' * 10}  **100%**"

    with patch.dict(DimboRate.user_overrides, {member.id: DimboRate.dimbo_defaults}):
        await member.send(allowed, "dimbo rate")
    embed = _last_embed(red_env, allowed)
    assert embed.title == "ERROR_CODE_4"
    assert embed.description == "User is too DIMBO to calculate."
    assert embed.color == discord.Color(0xFF0000)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_dom_rate_shows_submissive_ratings_positive_and_no_bar_when_mysterious(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    with patch.object(DomRate, "get_role_rating", return_value=-0.5):
        await member.send(allowed, "sub rate")
    embed = _last_embed(red_env, allowed)
    assert embed.title == "❯ Submissive"
    assert embed.description == f"member is 50% Submissive.\n\n{'🩷' * 5}{'⬛' * 5}  **50%**"
    assert embed.color == discord.Color(0xFF8FC8)

    with patch.object(DomRate, "get_role_rating", return_value=0.0):
        await member.send(allowed, "dom rate")
    assert _last_embed(red_env, allowed).description == "member is 1000% mysterious..."
    simcord.assert_no_errors(red_env)


class Roleplay(commands.Cog):
    """Stands in for the roleplay cog's counts."""

    def __init__(self, counts: Counter[str] | None) -> None:
        super().__init__()
        self.counts = counts

    async def action_counts(self, user_id: int) -> Counter[str] | None:
        return self.counts


class Unicornia(commands.Cog):
    """Stands in for the Unicornia cog's balance API."""

    async def get_balance(self, user_id: int) -> tuple[int, int]:
        return 999, 1


@pytest.mark.asyncio
async def test_horny_rate_goes_by_roleplay_counts_and_falls_back_to_the_daily_roll(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()
    roleplay = Roleplay(Counter(fuck=3, hug=1))
    await cast(Red, red_env.bot).add_cog(roleplay)

    await member.send(allowed, "horny rate")
    embed = _last_embed(red_env, allowed)
    assert embed.title == "❯ Down Bad"
    assert embed.description is not None and "75% horny" in embed.description
    assert "🔥" * 8 + "⬛" * 2 in embed.description
    assert embed.footer.text == "Calculated from roleplay stats."

    roleplay.counts = None  # untracked
    await member.send(allowed, "horny rate")
    embed = _last_embed(red_env, allowed)
    assert embed.description is not None and f"{daily_roll(member.id, 'horny')}% horny" in embed.description
    assert embed.footer.text is None
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_rich_rate_goes_by_the_unicornia_balance(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()
    await cast(Red, red_env.bot).add_cog(Unicornia())

    await member.send(allowed, "rich rate")
    embed = _last_embed(red_env, allowed)
    assert embed.title == "❯ Comfortable"
    assert embed.description is not None and embed.description.startswith("member is 50% rich.")
    assert embed.footer.text == "Going by wallet + bank."
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_rates_command_lists_the_topics_and_channels(red_env: simcord.Env) -> None:
    guild, allowed, _ = _world(red_env)
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()

    await member.send(allowed, "!rates")
    description = _last_embed(red_env, allowed).description or ""
    assert all(f"`{topic}`" in description for topic in ("stinky", "horny", "rich", "sub", "gremlin"))
    assert "`default`" not in description
    assert f"<#{allowed.id}>" in description
    simcord.assert_no_errors(red_env)
