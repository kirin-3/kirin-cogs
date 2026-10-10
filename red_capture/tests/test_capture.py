"""Run from python-bot/ (its redenv has Red and SimCord):

PYTHONPATH=../tools:. redenv/Scripts/python.exe -m pytest ../tools/red_capture/tests -q --rootdir=.
"""

import json
from typing import cast

import pytest
import simcord
from discord.http import Route
from redbot.core.bot import Red


@pytest.fixture
def red_cogs() -> list[str]:
    return ["red_capture"]


@pytest.mark.asyncio
async def test_captures_owner_commands_and_not_its_own_replies(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    owner = guild.add_member(red_env.create_user("owner"))
    other = guild.add_member(red_env.create_user("other"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    bot.owner_ids.add(owner.id)

    cog = bot.get_cog("RedCapture")
    assert cog is not None
    # SimCord swaps in its own HTTP client class; production keeps discord.py's, which is patched at load.
    cog.patch_http(type(bot.http))
    await owner.send(channel, "!capture start")
    await owner.send(channel, "!info")
    await other.send(channel, "!ping")  # someone else's command: not recorded
    await owner.send(channel, "!capture stop")
    await owner.send(channel, "!ping")  # after stop: not recorded

    lines = [json.loads(x) for x in cog.path.read_text(encoding="utf-8").splitlines()]
    kinds = [(e["kind"], e.get("content") or e.get("method")) for e in lines]
    assert kinds == [("command", "!info"), ("request", "POST")], lines
    embed = lines[1]["payload"]["embeds"][0]
    assert {f["name"] for f in embed["fields"]} >= {"Instance owned by", "About Red"}
    assert lines[1]["path"].startswith("v10/channels/") or "/channels/" in lines[1]["path"]
    simcord.assert_no_errors(red_env)


@pytest.mark.asyncio
async def test_captures_button_presses_and_their_responses(red_env: simcord.Env) -> None:
    bot = cast(Red, red_env.bot)
    guild = red_env.create_guild()
    owner = guild.add_member(red_env.create_user("owner"))
    channel = guild.create_text_channel("general")
    await red_env.settle()
    bot.owner_ids.add(owner.id)
    cog = bot.get_cog("RedCapture")
    assert cog is not None
    cog.patch_http(type(bot.http))
    await owner.send(channel, "!capture start")
    await owner.send(channel, "!set api")  # Red's own button flow, as a stand-in for a menu
    message = channel.last_message
    assert message is not None
    result = await owner.click(message, label="Set API token")
    assert result is not None

    lines = [json.loads(x) for x in cog.path.read_text(encoding="utf-8").splitlines()]
    kinds = [e["kind"] for e in lines]
    assert kinds[:2] == ["command", "request"], kinds
    assert "interaction" in kinds, kinds

    # SimCord answers interactions through its own adapter, so check the recording rule directly with
    # discord.py's real Route: a callback for an interaction of the capturing owner is kept...
    token = next(iter(cog._tokens))
    route = Route("POST", "/interactions/{webhook_id}/{webhook_token}/callback", webhook_id=1, webhook_token=token)
    cog._record_request(route, {"payload": {"type": 9}}, None, None)
    assert json.loads(cog.path.read_text(encoding="utf-8").splitlines()[-1])["payload"] == {"type": 9}
    # ...and one for anybody else's is not.
    count = cog._count
    other = Route("POST", "/interactions/{webhook_id}/{webhook_token}/callback", webhook_id=2, webhook_token="other")
    cog._record_request(other, {"payload": {"type": 4}}, None, None)
    assert cog._count == count
