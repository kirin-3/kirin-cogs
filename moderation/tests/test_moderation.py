import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from moderation.moderation import (
    DELETED_MOD,
    MUTED_ROLE_ID,
    Moderation,
    audit_action,
    format_warnings,
    log_embed,
    split_roles,
    unmuted_roles,
)


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

    cog = Moderation.__new__(Moderation)
    cog.warnings_config = SimpleNamespace(member_from_ids=lambda g, u: Member())  # type: ignore[assignment]
    ctx = SimpleNamespace(guild=SimpleNamespace(id=1), send=send, embed_color=embed_color, author=None)
    user = SimpleNamespace(id=2, display_avatar=SimpleNamespace(url="https://cdn.discordapp.com/embed/avatars/0.png"))

    await Moderation.warnings.callback(cog, ctx, user)  # type: ignore[arg-type]

    embed = sent[0]["embed"]
    assert embed.description == "*This user has no warnings.*"
    assert embed.footer.text.startswith("0 warnings · 0 points")


@pytest.mark.asyncio
async def test_warn_dm_sent_only_for_saved_warning() -> None:
    class Member:
        async def warnings(self) -> dict:
            return {"111": {"points": 1, "description": "spam", "mod": 5}}

    cog = Moderation.__new__(Moderation)
    cog.warnings_config = SimpleNamespace(member_from_ids=lambda g, u: Member())  # type: ignore[assignment]
    member = MagicMock(spec=discord.Member, id=2)
    member.send = AsyncMock()
    command = SimpleNamespace(qualified_name="warn", cog_name="Warnings")
    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1, name="Unicornia", icon=None), command=command, args=[None, None, member]
    )

    ctx.message = SimpleNamespace(id=111, created_at=datetime.now(UTC))
    await cog.on_command_completion(ctx)  # type: ignore[arg-type]
    embed = member.send.await_args.kwargs["embed"]
    assert embed.description.startswith(
        "You have been warned in the **Unicornia Server** for the following reason:\n> spam\n\n"
    )
    assert embed.footer.text == "Use .mywarnings to see your warnings."

    member.send.reset_mock()
    ctx.message = SimpleNamespace(id=222)  # Red refused this warn, nothing was saved
    await cog.on_command_completion(ctx)  # type: ignore[arg-type]
    member.send.assert_not_awaited()


@dataclass(frozen=True)
class Role:
    id: int
    default: bool = False
    assignable: bool = True

    def is_default(self) -> bool:
        return self.default

    def is_assignable(self) -> bool:
        return self.assignable


def test_mute_strips_and_unmute_restores_roles() -> None:
    everyone, member_role, booster, muted = (
        Role(1, default=True),
        Role(2),
        Role(3, assignable=False),
        Role(MUTED_ROLE_ID),
    )

    keep, strip = split_roles([everyone, member_role, booster, muted])  # type: ignore[list-item]
    assert keep == [booster]  # bots can't remove managed roles
    assert strip == [2]  # Muted is never saved, so unmute can't hand it back

    # member_role still exists; the second saved role was deleted during the mute.
    roles, skipped = unmuted_roles([everyone, booster, muted], [member_role, None])  # type: ignore[list-item]
    assert set(roles) == {booster, member_role}
    assert skipped == 1


def _muted_member(roles: list, record: dict | None) -> tuple[Moderation, MagicMock, AsyncMock]:
    mute = AsyncMock(return_value=record)
    mute.set = AsyncMock()
    cog = Moderation.__new__(Moderation)
    cog.config = SimpleNamespace(member=lambda m: SimpleNamespace(mute=mute))  # type: ignore[assignment]
    cog._locks = defaultdict(asyncio.Lock)
    member = MagicMock(spec=discord.Member, id=9, roles=roles)
    member.guild.id = 1
    member.guild.get_member.return_value = member
    member.guild.get_role.return_value = Role(MUTED_ROLE_ID)
    member.edit = AsyncMock()
    return cog, member, mute


@pytest.mark.asyncio
async def test_enforce_takes_off_and_saves_roles_gained_while_muted() -> None:
    muted, onboarding_role, booster = Role(MUTED_ROLE_ID), Role(5), Role(3, assignable=False)
    cog, member, mute = _muted_member([Role(1, default=True), booster, onboarding_role], {"roles": [2], "until": None})

    await cog._enforce(member)  # Muted was removed by hand and a role was self-assigned

    mute.set.assert_awaited_once_with({"roles": [2, 5], "until": None})  # given back on unmute
    assert member.edit.await_args.kwargs["roles"] == [booster, muted]


@pytest.mark.asyncio
async def test_enforce_leaves_unmuted_and_expired_members_alone() -> None:
    for record in (None, {"roles": [2], "until": 1.0}):
        cog, member, mute = _muted_member([Role(5)], record)
        await cog._enforce(member)
        member.edit.assert_not_awaited()
        mute.set.assert_not_awaited()


def _user(name: str, user_id: int) -> MagicMock:
    user = MagicMock(spec=discord.User, id=user_id)
    user.configure_mock(**{"__str__.return_value": name})
    user.display_avatar.url = f"https://cdn.example/{user_id}.png"
    return user


def test_public_log_embed_matches_yagpdb_layout() -> None:
    member, mod = _user("milky_way", 5), _user("junny", 7)

    ban = log_embed("ban", member, mod, "Trolling in verification")
    assert (
        ban.description
        == "\N{HAMMER} **Banned** milky\\_way *(ID 5)*\n\N{PAGE FACING UP} **Reason:** Trolling in verification"
    )
    assert ban.author.name == "junny (ID 7)"
    assert ban.thumbnail.url == "https://cdn.example/5.png"  # the member's avatar

    mute = log_embed("smute", member, mod, None, discord.utils.utcnow() + timedelta(hours=2))
    description = mute.description or ""
    assert "**Duration:** 2 hours (ends <t:" in description
    assert description.endswith("**Reason:** No reason given.")


def test_audit_action_picks_bans_kicks_unbans_and_timeouts_only() -> None:
    kinds = discord.AuditLogAction
    later = discord.utils.utcnow() + timedelta(hours=1)

    def entry(action, **after):
        return SimpleNamespace(action=action, after=SimpleNamespace(**after))

    assert audit_action(entry(kinds.ban)) == ("ban", None)  # type: ignore[arg-type]
    assert audit_action(entry(kinds.kick)) == ("kick", None)  # type: ignore[arg-type]
    assert audit_action(entry(kinds.unban)) == ("unban", None)  # type: ignore[arg-type]
    assert audit_action(entry(kinds.member_update, timed_out_until=later)) == ("timeout", later)  # type: ignore[arg-type]
    assert audit_action(entry(kinds.member_update, timed_out_until=None)) == ("untimeout", None)  # type: ignore[arg-type]
    assert audit_action(entry(kinds.member_update, nick="new name")) is None  # type: ignore[arg-type]
    assert audit_action(entry(kinds.member_role_update)) is None  # type: ignore[arg-type]


class _CommandBot:
    """Just the command registry, keyed by name like discord.py's."""

    def __init__(self, warnings_cog=None) -> None:
        self.commands: dict = {}
        self.warnings_cog = warnings_cog

    def get_cog(self, name: str):
        return self.warnings_cog if name == "Warnings" else None

    def get_command(self, name: str):
        return self.commands.get(name)

    def remove_command(self, name: str):
        return self.commands.pop(name, None)

    def add_command(self, command) -> None:
        assert command.name not in self.commands, "discord.py would raise CommandRegistrationError"
        self.commands[command.name] = command


@pytest.mark.asyncio
async def test_warnings_command_is_shared_safely_with_reds_warnings_cog() -> None:
    red_command = SimpleNamespace(name="warnings")
    warnings_cog = SimpleNamespace(get_commands=lambda: [red_command])
    cog = Moderation.__new__(Moderation)
    cog.expire_mutes = MagicMock()  # type: ignore[method-assign]

    # Warnings isn't loaded yet: give the name up so it can load later.
    cog.bot = bot = _CommandBot()
    bot.add_command(cog.warnings)
    cog.sync_warnings()
    assert bot.get_command("warnings") is None

    # Warnings loaded (startup or a reload): take the name over from Red's command.
    bot.warnings_cog = warnings_cog
    bot.add_command(red_command)
    cog.sync_warnings()
    assert bot.get_command("warnings") is cog.warnings

    # Moderation unloads: d.py removes the name, then Red's command goes back.
    bot.remove_command("warnings")
    await cog.cog_unload()
    assert bot.get_command("warnings") is red_command
