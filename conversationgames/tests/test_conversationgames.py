"""The question lists, suggestion cleanup, and the cards, votes and suggestions on a real Red bot."""

from types import SimpleNamespace
from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from conversationgames import questions
from conversationgames.conversationgames import ConversationGames, clean
from conversationgames.views import read_review, review_embed


def test_built_in_questions_are_unique_and_well_formed() -> None:
    for pool in (questions.TRUTHS, questions.DARES, questions.WYR, questions.NHIE):
        assert pool and len(pool) == len(set(pool))
    assert all(q.startswith("...") for q in questions.NHIE)
    for first, second in questions.WYR:
        assert first and second and not first.startswith(".") and not second.endswith("?")
    # The live list had lost a comma between these two
    assert "Use the '&fuck' or '&suck' command on someone who you are attracted to here." in questions.DARES
    assert ("not be able to open any closed doors (locked or unlocked)", "not be able to close any open doors") in (
        questions.WYR
    )


def test_suggestions_are_cleaned_up() -> None:
    assert clean("wyr", ["Would you rather fly", "or swim?"]) == ("fly", "swim")
    assert clean("wyr", ["fly", "  "]) is None
    assert clean("nhie", ["Never have I ever... eaten a crayon"]) == "...eaten a crayon"
    assert clean("nhie", ["eaten a crayon"]) == "...eaten a crayon"
    assert clean("truth", ["  What's your secret?  "]) == "What's your secret?"
    assert clean("dare", [""]) is None


def test_review_posts_can_be_read_back() -> None:
    user = cast(discord.abc.User, SimpleNamespace(display_name="member", display_avatar=SimpleNamespace(url="")))
    assert read_review(review_embed("wyr", ("fly", "swim"), user)) == ("wyr", ("fly", "swim"))
    assert read_review(review_embed("truth", "Why?", user)) == ("truth", "Why?")
    assert read_review(discord.Embed(description="Why?")) is None


@pytest.fixture
def red_cogs() -> list[str]:
    return ["conversationgames"]


def _cog(env: simcord.Env) -> ConversationGames:
    cog = cast(Red, env.bot).get_cog("ConversationGames")
    assert isinstance(cog, ConversationGames)
    return cog


def _guild(env: simcord.Env, guild: simcord.GuildHandle) -> discord.Guild:
    found = cast(Red, env.bot).get_guild(guild.id)
    assert found is not None
    return found


def _last(channel: simcord.ChannelHandle) -> discord.Message:
    message = channel.last_message
    assert message is not None
    return message


def _labels(message: discord.Message) -> list[str]:
    return [str(getattr(item, "label", "")) for row in message.components for item in getattr(row, "children", [])]


@pytest.mark.asyncio
async def test_truth_card_pings_the_target_and_its_buttons_deal_new_cards(red_env: simcord.Env) -> None:
    guild = red_env.create_guild()
    alice = guild.add_member(red_env.create_user("alice"))
    bob = guild.add_member(red_env.create_user("bob"))
    channel = guild.create_text_channel("games")
    await red_env.settle()

    await alice.send(channel, f"!truth <@{bob.id}>")
    card = _last(channel)
    assert card.content == f"<@{bob.id}>"
    embed = card.embeds[0]
    assert embed.title == "Truth" and embed.description in questions.TRUTHS
    assert embed.author.name == "alice asks bob"
    assert _labels(card) == ["Truth", "Dare", "Random", "Suggest one"]

    await bob.click(card, label="Dare")
    dare = _last(channel).embeds[0]
    assert dare.title == "Dare" and dare.description in questions.DARES
    assert dare.footer.text == "For bob"
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_decks_do_not_repeat_until_every_question_is_drawn(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild = _guild(red_env, red_env.create_guild())
    await red_env.settle()

    drawn = [await cog.draw(guild, "dare") for _ in questions.DARES]

    assert sorted(drawn) == sorted(questions.DARES)
    assert await cog.draw(guild, "dare") in questions.DARES  # the deck reshuffles


@pytest.mark.asyncio
async def test_would_you_rather_counts_one_vote_each(red_env: simcord.Env) -> None:
    guild = red_env.create_guild()
    alice = guild.add_member(red_env.create_user("alice"))
    bob = guild.add_member(red_env.create_user("bob"))
    channel = guild.create_text_channel("games")
    await red_env.settle()

    await alice.send(channel, "!wyr")
    card = _last(channel)
    assert card.embeds[0].title == "Would you rather..."
    assert _labels(card)[:2] == ["🅰️ 0", "🅱️ 0"]

    await alice.click(card, label="🅰️ 0")
    await bob.click(_last(channel), label="🅰️ 1")
    assert _labels(_last(channel))[:2] == ["🅰️ 2", "🅱️ 0"]

    await bob.click(_last(channel), label="🅱️ 0")  # changing your mind moves your vote
    await alice.click(_last(channel), label="🅰️ 1")  # pressing your own choice again takes it back
    assert _labels(_last(channel))[:2] == ["🅰️ 0", "🅱️ 1"]

    await red_env.advance_time(15 * 60 + 1)  # the card stops taking votes but keeps the count
    items = [item for row in _last(channel).components for item in getattr(row, "children", [])]
    assert all(getattr(item, "disabled", False) for item in items)
    assert _labels(_last(channel))[:2] == ["🅰️ 0", "🅱️ 1"]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_suggestions_go_to_staff_and_approved_ones_join_the_deck(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild = red_env.create_guild()
    staff_role = guild.create_role("Staff", permissions=discord.Permissions(manage_guild=True))
    staff = guild.add_member(red_env.create_user("staff"), roles=[staff_role])
    member = guild.add_member(red_env.create_user("member"))
    games = guild.create_text_channel("games")
    review = guild.create_text_channel("review")
    await red_env.settle()

    await member.send(games, "!nhie")
    card = _last(games)
    shown = await member.click(card, label="Suggest one")
    assert shown.modal is not None
    closed = await member.submit_modal(shown, {"question": "Never have I ever eaten a crayon"})
    simcord.assert_responded(closed, content="Suggestions aren't open right now.", ephemeral=True)

    await member.send(games, f"!cgset reviewchannel {review.id}")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    await staff.send(games, f"!cgset reviewchannel {review.id}")

    shown = await member.click(card, label="Suggest one")
    sent = await member.submit_modal(shown, {"question": "Never have I ever eaten a crayon"})
    simcord.assert_responded(sent, ephemeral=True)
    suggestion = _last(review)
    assert suggestion.embeds[0].description == "...eaten a crayon"
    assert suggestion.content == f"Suggested by <@{member.id}>"

    refused = await member.click(suggestion, label="Approve")
    simcord.assert_responded(refused, content="Only staff can review suggestions.", ephemeral=True)

    await staff.click(suggestion, label="Approve")
    assert _last(review).embeds[0].title == "Approved: Never have I ever..."
    assert (await cog.config.guild_from_id(guild.id).custom())["nhie"] == ["...eaten a crayon"]
    assert "...eaten a crayon" in await cog.pool(_guild(red_env, guild), "nhie")
    simcord.assert_no_errors(red_env)
