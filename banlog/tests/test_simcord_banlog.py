"""Real Discord messages and deletions reach the ban snapshot store."""

from typing import cast
from unittest.mock import patch

import pytest
import simcord
from redbot.core.bot import Red

from banlog.banlog import BanLog


@pytest.fixture
def red_cogs() -> list[str]:
    return ["banlog"]


@pytest.mark.asyncio
async def test_message_delete_is_saved_and_included_in_ban_snapshot(red_env: simcord.Env) -> None:
    cog = cast(Red, red_env.bot).get_cog("BanLog")
    assert isinstance(cog, BanLog)
    guild = red_env.create_guild()
    member = guild.add_member(red_env.create_user("member"))
    channel = guild.create_text_channel("general")
    await red_env.settle()

    with patch("banlog.banlog.GUILD_ID", guild.id):
        message = await member.send(channel, "last words", attachments=[("proof.txt", b"evidence")])
        await member.delete(message)
        await cog._flush()

    ban_id = await cog.record_ban(member.id, "member", None, "spam", message.created_at.timestamp() + 1)
    ban = await cog.get_ban(ban_id)
    assert ban is not None
    assert ban["user_id"] == member.id
    assert len(ban["messages"]) == 1
    saved = ban["messages"][0]
    assert saved["content"] == "last words"
    assert saved["attachments"] == ["proof.txt"]
    assert saved["deleted_at"] is not None
    simcord.assert_no_errors(red_env)
