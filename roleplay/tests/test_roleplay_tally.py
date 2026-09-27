"""Roleplay action counts: the helpers, and counting, [p]rpstats and opting out on a real Red bot."""

from collections import Counter
from typing import cast

import discord
import pytest
import simcord
from redbot.core.bot import Red

from roleplay.main import Roleplay
from roleplay.tally import Pairs, member_stats, summary, top_pairs


def test_member_stats_split_given_received_and_partners() -> None:
    pairs: Pairs = {(1, 2): Counter(hug=3, pat=1), (2, 1): Counter(kiss=2), (3, 1): Counter(hug=1)}

    given, received, partners = member_stats(pairs, 1)

    assert given == Counter(hug=3, pat=1)
    assert received == Counter(kiss=2, hug=1)
    assert partners == Counter({2: 6, 3: 1})


def test_top_pairs_count_both_directions_busiest_first() -> None:
    pairs: Pairs = {(1, 2): Counter(hug=3), (2, 1): Counter(hug=2, kiss=1), (3, 4): Counter(pat=5)}

    ranked = top_pairs(pairs, 10)

    assert [(a, b, counts.total()) for a, b, counts in ranked] == [(1, 2, 6), (3, 4, 5)]
    assert ranked[0][2] == Counter(hug=5, kiss=1)
    assert len(top_pairs(pairs, 1)) == 1


def test_summary_lists_the_top_actions() -> None:
    assert summary(Counter(hug=1200, pat=10, kiss=3, poke=1)) == "hug **1,200** · pat **10** · kiss **3**"


@pytest.fixture
def red_cogs() -> list[str]:
    return ["roleplay"]


def _cog(env: simcord.Env) -> Roleplay:
    cog = cast(Red, env.bot).get_cog("Roleplay")
    assert isinstance(cog, Roleplay)
    return cog


def _last(channel: simcord.ChannelHandle) -> discord.Message:
    message = channel.last_message
    assert message is not None
    return message


async def _public(cog: Roleplay, *members: simcord.MemberActor) -> None:
    """Public members consent to everything, so actions on them go through without a question."""
    for member in members:
        await cog.user_settings.config.user_from_id(member.id).public.set(True)
        await cog.user_settings.config.user_from_id(member.id).servant.set(True)


@pytest.mark.asyncio
async def test_completed_actions_are_counted_and_shown(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild = red_env.create_guild()
    alice = guild.add_member(red_env.create_user("alice"))
    bob = guild.add_member(red_env.create_user("bob"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await _public(cog, alice, bob)

    await alice.send(channel, f"!hug <@{bob.id}>")
    await red_env.advance_time(121)  # action commands have a per-channel cooldown
    await alice.send(channel, f"!hug <@{bob.id}>")
    await red_env.advance_time(121)
    await alice.send(channel, f"!ask pat <@{bob.id}>")  # asked for: bob pats alice
    await red_env.advance_time(121)
    await alice.send(channel, "!hug")  # performed by the bot, not counted

    assert await cog.tally.pairs() == {(alice.id, bob.id): Counter(hug=2), (bob.id, alice.id): Counter(pat=1)}

    await alice.send(channel, "!rpstats")
    fields = {field.name: field.value for field in _last(channel).embeds[0].fields}
    assert fields["Given (2)"] == "hug **2**"
    assert fields["Received (1)"] == "pat **1**"
    assert fields["Favourite partners"] == "bob: **3**"

    await bob.send(channel, f"!rpstats <@{alice.id}> <@{bob.id}>")
    embed = _last(channel).embeds[0]
    assert embed.description == "**3** actions between them."
    assert [field.value for field in embed.fields] == ["hug **2**", "pat **1**"]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_untracked_members_are_not_counted_and_their_counts_are_deleted(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    guild = red_env.create_guild()
    alice = guild.add_member(red_env.create_user("alice"))
    bob = guild.add_member(red_env.create_user("bob"))
    carol = guild.add_member(red_env.create_user("carol"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    await _public(cog, alice, bob, carol)
    await cog.tally.record(alice.id, bob.id, "hug")
    await cog.tally.record(carol.id, alice.id, "pat")
    await cog.tally.record(carol.id, bob.id, "kiss")

    await alice.send(channel, "!roleplay settings untracked true")
    assert await cog.tally.pairs() == {(carol.id, bob.id): Counter(kiss=1)}

    await bob.send(channel, f"!hug <@{alice.id}>")
    assert await cog.tally.pairs() == {(carol.id, bob.id): Counter(kiss=1)}

    await bob.send(channel, f"!rpstats <@{alice.id}>")
    assert _last(channel).content == "**alice** keeps their roleplay stats private."

    await cog.red_delete_data_for_user(requester="user", user_id=carol.id)
    assert await cog.tally.pairs() == {}
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_member_site_gets_stats_and_top_pairs_as_ids(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    await cog.tally.record(1, 2, "hug")
    await cog.tally.record(2, 1, "kiss")
    await cog.tally.record(3, 1, "pat")

    stats = await cog.stats_for(1)
    assert stats == {
        "untracked": False,
        "given": [("hug", 1)],
        "given_total": 1,
        "received": [("kiss", 1), ("pat", 1)],
        "received_total": 2,
        "partners": [(2, 2), (3, 1)],
    }
    assert (await cog.top_pairs())[0] == {"a": 1, "b": 2, "total": 2, "actions": [("hug", 1), ("kiss", 1)]}

    await cog.set_toggle(1, "untracked", True)
    assert await cog.stats_for(1) == {"untracked": True}
    assert await cog.top_pairs() == []
