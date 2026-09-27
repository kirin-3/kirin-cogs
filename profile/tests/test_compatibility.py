"""[p]compat scoring, and the command on a real Red bot."""

from profile.compatibility import SWITCH_ROLE, bar, kinks_in, score, side, verdict
from profile.profile import Profile
from typing import cast

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

DOM = 686097057190379537
SUB = 686097362107498504
PETPLAY = 903170628213944321


def test_kinks_are_read_from_free_text_in_any_spelling() -> None:
    assert kinks_in("Petplay, orgasm denial and being tied up!") == {"pet play", "orgasm control", "bondage"}
    assert kinks_in("pet play\nhypno") == {"pet play", "hypnosis"}
    assert kinks_in("a little bit of everything") == frozenset()
    assert kinks_in(None) == frozenset()


def test_lean_comes_from_roles_and_the_role_answer() -> None:
    assert side({}, [DOM]).lean == 1
    assert side({"role": "Submissive"}, []).lean == -1
    assert side({"role": "switch leaning sub"}, []).lean == -0.5
    assert side({}, [SWITCH_ROLE]).switch
    assert side({}, []).lean is None
    assert side("not a dict", [123]).known is False


def test_a_dom_and_a_sub_with_shared_kinks_beat_two_subs() -> None:
    dom = side({"kinks": "bondage, praise, spanking", "likes": "gaming, music"}, [DOM])
    sub = side({"kinks": "praise, bondage, spanking", "likes": "video games, reading"}, [SUB])
    other_sub = side({"kinks": "praise, bondage, spanking", "likes": "video games"}, [SUB])
    pair, same_side = score(dom, sub), score(sub, other_sub)
    assert pair is not None and same_side is not None
    assert pair > same_side
    assert pair >= 75


def test_a_kink_on_the_other_members_limits_costs_points() -> None:
    dom = side({"kinks": "bondage, watersports"}, [DOM])
    sub = side({"kinks": "bondage", "limits": "scat, piss"}, [SUB])
    easy_sub = side({"kinks": "bondage", "limits": "scat"}, [SUB])
    clash, clean = score(dom, sub), score(dom, easy_sub)
    assert clash is not None and clean is not None
    assert clean - clash == 15


def test_sharing_a_kink_role_counts_more_than_writing_the_kink() -> None:
    written = score(side({"kinks": "pet play"}, []), side({"kinks": "pet play"}, []))
    role = score(side({}, [PETPLAY]), side({}, [PETPLAY]))
    assert written is not None and role is not None
    assert role > written


def test_nothing_comparable_gives_no_score() -> None:
    assert score(side({}, [DOM]), side({"kinks": "bondage"}, [])) is None


def test_every_score_has_a_verdict_and_a_bar() -> None:
    for percent in range(101):
        assert verdict(percent)
        assert len(bar(percent)) == 10


def last(channel: simcord.ChannelHandle) -> discord.Message:
    message = channel.last_message
    assert message is not None
    return message


@pytest.fixture
def red_cogs() -> list[str]:
    return ["profile"]


@pytest.mark.asyncio
async def test_compat_command_shows_only_the_score(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("Profile")
    assert isinstance(cog, Profile)
    guild = red_env.create_guild()
    alice = guild.add_member(red_env.create_user("alice"))
    bob = guild.add_member(red_env.create_user("bob"))
    stranger = guild.add_member(red_env.create_user("stranger"))
    channel = guild.create_text_channel("bot-commands")
    await red_env.settle()
    await cog.config.member_from_ids(guild.id, alice.id).profile_data.set(
        {"role": "Dom", "kinks": "bondage, praise", "likes": "music"}
    )
    await cog.config.member_from_ids(guild.id, bob.id).profile_data.set(
        {"role": "sub", "kinks": "praise and bondage", "likes": "music, cooking"}
    )

    await alice.send(channel, f"!compat {bob.id}")
    embed = last(channel).embeds[0]
    assert embed.description is not None
    assert "%" in embed.description
    assert "bondage" not in embed.description and "praise" not in embed.description

    await red_env.advance_time(61)
    await alice.send(channel, f"!compat {stranger.id}")
    assert "Not enough to go on for **stranger**" in last(channel).content

    await red_env.advance_time(61)
    await stranger.send(channel, f"!compat {alice.id} {bob.id}")
    assert last(channel).embeds[0].description == embed.description
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_compat_has_a_one_minute_cooldown_per_channel_and_per_member(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    alice = guild.add_member(red_env.create_user("alice"))
    bob = guild.add_member(red_env.create_user("bob"))
    general = guild.create_text_channel("general")
    other = guild.create_text_channel("other")
    await red_env.settle()

    def answers(channel: simcord.ChannelHandle) -> int:
        """Compat's own replies, not Red's cooldown and usage messages."""
        assert bot.user is not None
        return sum(
            1
            for message in channel.history()
            if message.author.id == bot.user.id and (message.embeds or "Not enough to go on" in message.content)
        )

    await bob.send(general, "!compat nobody")  # a mistyped member doesn't use up the channel's minute
    assert isinstance(red_env.errors.pop(), commands.BadArgument)
    await alice.send(general, f"!compat {bob.id}")
    assert answers(general) == 1

    await bob.send(general, f"!compat {alice.id}")
    error = red_env.errors.pop()
    assert isinstance(error, commands.CommandOnCooldown) and error.type is commands.BucketType.channel

    await alice.send(other, f"!compat {bob.id}")
    error = red_env.errors.pop()
    assert isinstance(error, commands.CommandOnCooldown) and error.type is commands.BucketType.user
    await bob.send(other, f"!compat {alice.id}")  # alice's refused try didn't use up this channel's minute
    assert answers(other) == 1

    await red_env.advance_time(61)
    await alice.send(general, f"!compat {bob.id}")
    assert answers(general) == 2
    simcord.assert_no_errors(red_env)
