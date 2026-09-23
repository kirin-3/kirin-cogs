from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from warnlist.warnlist import DELETED_MOD, WarnList, format_warnings


def key(y: int, m: int, d: int) -> str:
    return str(discord.utils.time_snowflake(datetime(y, m, d, tzinfo=UTC)))


def test_format_orders_dates_and_strips_yagpdb_suffix() -> None:
    old, new = key(2020, 6, 28), key(2024, 3, 11)
    warnings = {
        new: {"points": 2, "description": "native warn", "mod": 5},
        old: {"points": 0, "description": "spam\nagain (YAGPDB, 2020-06-28, by Mod#0001)", "mod": 99},
        "junk": {"description": None, "mod": DELETED_MOD},
    }
    first, second, third = format_warnings(warnings, lambda mod_id: "<@5>" if mod_id == 5 else None)

    # Newest first, numbered chronologically; key without a snowflake sorts oldest.
    assert first.startswith("**#3** · <t:1710115200:D>")
    assert "Mod: <@5> · 2 points · ID" in first
    assert second.startswith("**#2** · <t:1593302400:D>")
    assert "> spam\n> again\nMod: Mod#0001 · YAGPDB · ID" in second
    assert "(YAGPDB" not in second
    assert third == "**#1** · unknown date\n> No reason given.\nMod: Deleted moderator · ID `junk`"


@pytest.mark.asyncio
async def test_warnings_replies_for_user_without_warnings() -> None:
    sent: list[dict] = []

    class Member:
        async def all(self) -> dict:
            return {"total_points": 0, "status": "", "warnings": {}}

    async def send(**kwargs) -> None:
        sent.append(kwargs)

    async def embed_color() -> discord.Color:
        return discord.Color.blurple()

    cog = WarnList.__new__(WarnList)
    cog.config = SimpleNamespace(member_from_ids=lambda g, u: Member())  # type: ignore[assignment]
    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), send=send, embed_color=embed_color, author=None)
    user = SimpleNamespace(id=2, display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/embed/avatars/0.png"))

    await WarnList.warnings.callback(cog, ctx, user)  # type: ignore[arg-type]

    embed = sent[0]["embed"]
    assert embed.description == "*This user has no warnings.*"
    assert embed.footer.text.startswith("0 warnings · 0 points")


@pytest.mark.asyncio
async def test_warn_dm_sent_only_for_saved_warning() -> None:
    class Member:
        async def warnings(self) -> dict:
            return {"111": {"points": 1, "description": "spam", "mod": 5}}

    async def embed_color() -> discord.Color:
        return discord.Color.red()

    cog = WarnList.__new__(WarnList)
    cog.config = SimpleNamespace(member_from_ids=lambda g, u: Member())  # type: ignore[assignment]
    member = MagicMock(spec=discord.Member, id=2)
    member.send = AsyncMock()
    command = SimpleNamespace(qualified_name="warn", cog_name="Warnings")
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1), command=command, args=[None, None, member], embed_color=embed_color
    )

    ctx.message = SimpleNamespace(id=111)
    await cog.on_command_completion(ctx)  # type: ignore[arg-type]
    description = member.send.await_args.kwargs["embed"].description
    assert description.startswith("You have been warned in the Unicornia Server for the following reason:\nspam\n\n")

    member.send.reset_mock()
    ctx.message = SimpleNamespace(id=222)  # Red refused this warn, nothing was saved
    await cog.on_command_completion(ctx)  # type: ignore[arg-type]
    member.send.assert_not_awaited()
