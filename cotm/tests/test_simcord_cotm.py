"""Contest command checks on a real Red bot."""

from typing import cast

import pytest
import simcord
from redbot.core import commands
from redbot.core.bot import Red

from cotm.main import ContestCog


@pytest.fixture
def red_cogs() -> list[str]:
    return ["cotm"]


@pytest.mark.asyncio
async def test_contest_requires_admin_and_persists_number(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("ContestCog")
    assert isinstance(cog, ContestCog)
    owner_user = red_env.create_user("owner")
    guild = red_env.create_guild(owner=owner_user)
    owner = guild.add_member(owner_user)
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("contest")
    await red_env.settle()

    await member.send(channel, "!contest 7")
    assert isinstance(red_env.errors.pop(), commands.CheckFailure)
    assert await cog.config.contest_number() == 1

    await owner.send(channel, "!contest 7")
    assert await cog.config.contest_number() == 7
    dashboards = await cog.config.dashboards()
    assert len(dashboards) == 1
    assert next(iter(dashboards.values())) == 7
    dashboard = next(message for message in channel.history() if str(message.id) in dashboards)
    await member.click(dashboard, label="Terms")
    updated = channel.last_message
    assert updated is not None
    assert any("Entry Terms" in str(component) for component in updated.components)
    simcord.assert_no_errors(red_env)
