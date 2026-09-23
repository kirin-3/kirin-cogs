from datetime import UTC, datetime

import discord

from warnlist.warnlist import DELETED_MOD, format_warnings


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
