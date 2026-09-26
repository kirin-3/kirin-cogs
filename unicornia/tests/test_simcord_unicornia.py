"""Unicornia on a real Red instance driven through SimCord.

Covers the Discord-facing flows over the real SQLite database: balance, the
daily reward, transfers, the bank modal behind the balance view's buttons, the
message XP listener, and the channel whitelist. The systems' math has its own
unit tests; these check the wiring a command actually goes through.
"""

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import discord
import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

import unicornia.systems.currency_systems
import unicornia.systems.xp_system
import unicornia.unicornia
from unicornia.systems.card_generator import XPCardGenerator
from unicornia.unicornia import Unicornia

# unicornia derives its on-disk locations from these modules' __file__: the
# SQLite DB (unicornia.unicornia), the font cache and xp_config.yml
# (xp_system, via XPCardGenerator), and the currency spawn images
# (currency_systems). The fixture below redirects all of them into tmp_path.
_PATH_MODULES = (
    unicornia.unicornia,
    unicornia.systems.xp_system,
    unicornia.systems.currency_systems,
)


@pytest.fixture
def red_cogs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Load unicornia with every file it writes pointed at tmp_path, offline."""
    data_dir = tmp_path / "unicornia-data"
    for module in _PATH_MODULES:
        monkeypatch.setattr(module, "__file__", str(data_dir / (module.__name__.rsplit(".", 1)[-1] + ".py")))
    # The bundled-font download on first load would hit GitHub.
    monkeypatch.setattr(XPCardGenerator, "_ensure_bundled_fonts", AsyncMock())
    return ["unicornia"]


def _cog(env: simcord.Env) -> Unicornia:
    cog = cast(Red, env.bot).get_cog("Unicornia")
    assert isinstance(cog, Unicornia)
    return cog


def _bot_messages(channel: simcord.ChannelHandle, bot: Red) -> list[discord.Message]:
    assert bot.user is not None
    return [m for m in channel.history() if m.author.id == bot.user.id]


def _member(actor: simcord.MemberActor) -> discord.Member:
    """The actor's discord.py member, the way the cog sees it."""
    member = actor.member
    assert member is not None
    return member


def _last_text(channel: simcord.ChannelHandle, bot: Red) -> str:
    messages = _bot_messages(channel, bot)
    assert messages, "the bot did not reply"
    return messages[-1].content or ""


def _modal_text_input_ids(shown: simcord.InteractionResult) -> list[str]:
    assert shown.modal is not None
    return [item["custom_id"] for row in shown.modal["components"] for item in row["components"]]


def _guild_with_owner(env: simcord.Env) -> tuple[simcord.GuildHandle, simcord.MemberActor]:
    """A guild plus a member who passes Red's owner checks, as --owner would."""
    guild = env.create_guild()
    owner = guild.add_member(env.create_user("owner"))
    # discord.py types owner_ids as a bare Collection; Red keeps a set there.
    cast(set[int], cast(Red, env.bot).owner_ids).add(owner.id)
    return guild, owner


@pytest.mark.asyncio
async def test_balance_replies_with_an_empty_wallet_embed(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, _owner = _guild_with_owner(red_env)
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!balance")

    reply = _bot_messages(channel, bot)[-1]
    assert reply.embeds, "expected a balance embed"
    embed = reply.embeds[0]
    assert embed.title == "member's Balance"
    fields = {f.name: f.value or "" for f in embed.fields}
    assert fields["👛 Wallet"].endswith("0")
    assert fields["🏦 Bank"].endswith("0")
    assert fields["💰 Total"].endswith("0")
    wallet, bank = await _cog(red_env).get_balance(member.id)
    assert (wallet, bank) == (0, 0)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_timely_pays_once_per_cooldown(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, _owner = _guild_with_owner(red_env)
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!timely")
    reply = _bot_messages(channel, bot)[-1]
    assert reply.embeds and reply.embeds[0].title == "💰 Daily Reward Claimed!"
    wallet, _bank = await _cog(red_env).get_balance(member.id)
    assert wallet > 0

    # The cooldown is 24h; the second claim right after must refuse and leave
    # the balance alone.
    await member.send(channel, "!timely")
    assert "You've already claimed your daily reward" in _last_text(channel, bot)
    wallet_after, _bank = await _cog(red_env).get_balance(member.id)
    assert wallet_after == wallet
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_economy_give_moves_currency_between_members(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, _owner = _guild_with_owner(red_env)
    giver = guild.add_member(red_env.create_user("giver"))
    receiver = guild.add_member(red_env.create_user("receiver"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await giver.send(channel, "!timely")
    wallet, _bank = await _cog(red_env).get_balance(giver.id)
    assert wallet > 200

    await giver.send(channel, f"!economy give 200 {_member(receiver).mention}")
    assert "You gave" in _last_text(channel, bot) and "200" in _last_text(channel, bot)
    assert await _cog(red_env).get_balance(receiver.id) == (200, 0)

    await giver.send(channel, f"!economy give 500000 {_member(receiver).mention}")
    assert "You don't have enough" in _last_text(channel, bot)
    assert await _cog(red_env).get_balance(receiver.id) == (200, 0)
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_bank_deposit_through_the_balance_view_modal(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, _owner = _guild_with_owner(red_env)
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "!timely")
    await member.send(channel, "!balance")
    balance_reply = next(m for m in reversed(_bot_messages(channel, bot)) if m.embeds)

    shown = await member.click(balance_reply, label="Deposit")
    assert shown.modal is not None
    (amount_id,) = _modal_text_input_ids(shown)

    done = await member.submit_modal(shown, {amount_id: "200"})
    assert done.response is not None
    assert "Deposited" in done.response.content and "200" in done.response.content
    assert done.response.ephemeral

    wallet, bank = await _cog(red_env).get_balance(member.id)
    assert bank == 200
    assert wallet > 0  # the timely payout minus the deposit
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_messages_gain_xp_only_in_included_channels(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, owner = _guild_with_owner(red_env)
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    await member.send(channel, "hello there")
    await member.send(channel, "!level lb")
    assert "No XP data found" in _last_text(channel, bot)

    # Only the Red owner passes the admin() check on the guild config group.
    await owner.send(channel, f"!unicornia guild xp include {channel.id}")
    assert "added to XP whitelist" in _last_text(channel, bot)

    await member.send(channel, "hello again")
    # Message XP is buffered and flushed to SQLite by a 30s background task.
    await red_env.advance_time(31)
    _cog(red_env).xp_system._leaderboard_cache.clear()  # the ranking is otherwise reused for a minute
    await member.send(channel, "!level lb")
    reply = _bot_messages(channel, bot)[-1]
    assert reply.embeds, "expected a leaderboard embed"
    leaderboard = reply.embeds[0].description or ""
    assert "**member**" in leaderboard
    assert "3 XP" in leaderboard  # xp_per_message default
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_command_whitelist_restricts_balance_to_one_channel(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, owner = _guild_with_owner(red_env)
    member = guild.add_member(red_env.create_user("member"))
    general = guild.create_text_channel("general")
    bots = guild.create_text_channel("bot-commands")
    await red_env.settle()

    await owner.send(general, f"!unicornia whitelist command add balance {bots.id}")
    assert "is now allowed" in _last_text(general, bot)

    # cog_check() quietly fails in the unlisted channel: no reply, just the
    # expected CheckFailure for the test to consume.
    replies_before = len(_bot_messages(general, bot))
    await member.send(general, "!balance")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    assert len(_bot_messages(general, bot)) == replies_before

    await member.send(bots, "!balance")
    assert _bot_messages(bots, bot)[-1].embeds
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_xpshop_buy_and_use_reply_as_before(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild, _owner = _guild_with_owner(red_env)
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    cog = _cog(red_env)
    cog.xp_system.card_generator.xp_config = {
        "shop": {
            "bgs": {
                "default": {"name": "Default Background", "price": 0, "url": "https://x/default.png"},
                "astolfo": {"name": "Astolfo", "price": 20_000, "url": "https://x/Astolfo.gif"},
                "aki": {"name": "Aki", "price": 20_000, "url": "https://x/aki.gif", "hidden": True},
            }
        }
    }
    symbol = await cog.config.currency_symbol()

    await member.send(channel, "!xpshop buy astolfo")
    assert _last_text(channel, bot).endswith("Insufficient Slut points! You have 0 but need 20,000.")

    await cog.add_balance(member.id, 25_000)
    await member.send(channel, "!xpshop buy astolfo")
    assert _last_text(channel, bot) == (
        f"✅ Successfully purchased **Astolfo** for 20,000 {symbol}!"
        "\n🌟 Auto-equipped **Astolfo** as your new background!"
    )
    await member.send(channel, "!xpshop buy astolfo")
    assert _last_text(channel, bot).endswith("You already own this background!")
    await member.send(channel, "!xpshop buy aki")
    assert _last_text(channel, bot).endswith("Background `aki` is not available for purchase.")

    await member.send(channel, "!xpshop use aki")
    assert "You don't own the background `aki`." in _last_text(channel, bot)
    await member.send(channel, "!xpshop use default")
    assert _last_text(channel, bot) == "✅ Now using **Default Background** as your XP background!"
    assert await cog.equipped_backgrounds([member.id]) == {member.id: "default"}
    assert await cog.get_balance(member.id) == (5_000, 0)
    simcord.assert_no_errors(red_env)
