"""A boost gateway event settles one Nitro reward."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import discord
import pytest
import simcord
from redbot.core.bot import Red
from simcord.backend import serializers

from nitroaward.nitroaward import AWARD_AMOUNT, NitroAward


@pytest.fixture
def red_cogs() -> list[str]:
    return ["nitroaward"]


@pytest.mark.asyncio
async def test_boost_update_credits_once_and_saves_timestamp(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("NitroAward")
    assert isinstance(cog, NitroAward)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("booster"))
    await red_env.settle()

    operation = AsyncMock(return_value=SimpleNamespace(state="settled"))
    unicornia = SimpleNamespace(apply_operation=operation)
    real_get_cog = bot.get_cog
    backend = red_env.backend
    guild_model = backend.get_guild(guild.id)
    payload = dict(serializers.member_payload(backend, guild_model, guild_model.members[member.id]))
    payload["guild_id"] = str(guild.id)
    boosted_at = discord.utils.utcnow()
    payload["premium_since"] = boosted_at.isoformat()

    with patch.object(
        bot, "get_cog", side_effect=lambda name: unicornia if name == "Unicornia" else real_get_cog(name)
    ):
        backend.emit("GUILD_MEMBER_UPDATE", payload)
        await red_env.settle()
        backend.emit("GUILD_MEMBER_UPDATE", payload)
        await red_env.settle()

    operation.assert_awaited_once_with(
        key=f"nitro:{guild.id}:{member.id}:{boosted_at.timestamp()}",
        user_id=member.id,
        amount=AWARD_AMOUNT,
        direction="credit",
        source="nitroaward",
        guild_id=guild.id,
        reason="Nitro Boost Reward",
    )
    group = cog.config.member_from_ids(guild.id, member.id)
    assert await group.last_boost_timestamp() == boosted_at.timestamp()
    assert await group.pending_boost_timestamp() is None
    simcord.assert_no_errors(red_env)
