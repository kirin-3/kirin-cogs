"""VerifyUser permission and role assignment through Red commands."""

from typing import cast
from unittest.mock import patch

import pytest
import simcord
from redbot.core.bot import Red

from verifyuser.verifyuser import VerifyUser


@pytest.fixture
def red_cogs() -> list[str]:
    return ["verifyuser"]


@pytest.mark.asyncio
async def test_authorized_member_verifies_once(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    cog = bot.get_cog("VerifyUser")
    assert isinstance(cog, VerifyUser)
    guild = red_env.create_guild()
    verification_role = guild.create_role("Verified")
    authorized_role = guild.create_role("Verifier")
    verifier = guild.add_member(red_env.create_user("verifier"), roles=[authorized_role])
    target = guild.add_member(red_env.create_user("target"))
    bystander = guild.add_member(red_env.create_user("bystander"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    with (
        patch.object(VerifyUser, "AUTHORIZED_ROLE_ID", authorized_role.id),
        patch.object(VerifyUser, "VERIFICATION_ROLE_ID", verification_role.id),
    ):
        await bystander.send(channel, f"!verifyuser {target.id}")
        simcord.assert_sent(channel, contains="don't have permission")
        current_target = target.member
        assert current_target is not None
        assert current_target.get_role(verification_role.id) is None

        await verifier.send(channel, f"!verifyuser {verifier.id}")
        simcord.assert_sent(channel, contains="cannot use this command on yourself")

        await verifier.send(channel, f"!verifyuser {target.id}")
        simcord.assert_sent(channel, contains=f"Successfully verified <@{target.id}>!")
        updated_target = target.member
        assert updated_target is not None
        assert updated_target.get_role(verification_role.id) is not None

        await verifier.send(channel, f"!verifyuser {target.id}")
        simcord.assert_sent(channel, contains="already verified")

    simcord.assert_no_errors(red_env)
