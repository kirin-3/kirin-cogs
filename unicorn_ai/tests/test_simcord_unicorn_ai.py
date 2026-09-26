from typing import cast

import pytest
import simcord
from redbot.core.bot import Red

from unicorn_ai.unicorn_ai import UnicornAI


@pytest.fixture
def red_cogs() -> list[str]:
    return ["unicorn_ai"]


def _cog(red_env: simcord.Env) -> UnicornAI:
    cog = cast(Red, red_env.bot).get_cog("UnicornAI")
    assert isinstance(cog, UnicornAI)
    return cog


@pytest.mark.asyncio
async def test_read_messages_switch_is_the_inverse_of_the_opt_out(red_env: simcord.Env) -> None:
    cog = _cog(red_env)
    assert (await cog.settings_for(1))["read_messages"]["value"] is True

    await cog.set_toggle(1, "read_messages", False)
    assert await cog.config.user_from_id(1).opt_out() is True
    assert (await cog.settings_for(1))["read_messages"]["value"] is False

    await cog.set_toggle(1, "read_messages", True)
    assert await cog.config.all_users() == {}
    with pytest.raises(ValueError):
        await cog.set_toggle(1, "daddy", False)


@pytest.mark.asyncio
async def test_aioptout_flips_the_flag_the_site_shows(red_env: simcord.Env) -> None:
    guild = red_env.create_guild()
    channel = guild.create_text_channel("general")
    member = guild.add_member(red_env.create_user("member"))
    await red_env.settle()
    cog = _cog(red_env)

    await member.send(channel, "!aioptout")
    assert (await cog.settings_for(member.id))["read_messages"]["value"] is False

    await cog.set_toggle(member.id, "read_messages", True)
    await member.send(channel, "!aioptout")
    assert await cog.config.user_from_id(member.id).opt_out() is True
    simcord.assert_no_errors(red_env)
