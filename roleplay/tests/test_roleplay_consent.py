"""Covers asking for consent (the rules themselves are in test_roleplay_decide), the
consent buttons, looking up members, action lookup and reloading
the cog."""

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands as dpy_commands

from roleplay import const
from roleplay import main as main_module
from roleplay import settings as settings_module
from roleplay.actions import ActionManager
from roleplay.main import Roleplay
from roleplay.users import Manager
from roleplay.views import ConsentView


class _Member:
    def __init__(self, member_id: int, *, bot: bool = False) -> None:
        self.id = member_id
        self.bot = bot
        self.display_name = f"member{member_id}"
        self.mention = f"<@{member_id}>"


def _cog(settings: dict[int, dict[str, Any]], owners: dict[int, _Member]) -> Roleplay:
    """A Roleplay cog whose members have the given settings and owners."""

    def user(member: _Member) -> SimpleNamespace:
        return SimpleNamespace(all=AsyncMock(return_value=settings.get(member.id, {})))

    async def get_owner(_ctx: Any, member: _Member, _owner_ids: list[int]) -> _Member | None:
        return owners.get(member.id)

    cog = Roleplay.__new__(Roleplay)
    cog.bot = MagicMock()
    cog.logger = logging.getLogger("test_roleplay")
    cog.action_manager = ActionManager()
    cog.user_settings = cast(
        Any,
        SimpleNamespace(config=SimpleNamespace(user=user), users_manager=SimpleNamespace(get_owner=get_owner)),
    )
    cog.send_action_message = AsyncMock()
    cog.tally = cast(Any, SimpleNamespace(record=AsyncMock()))
    return cog


def _consent(monkeypatch: pytest.MonkeyPatch, *answers: tuple[bool | None, int | None]) -> AsyncMock:
    """Answer each consent request in turn with (result, declined_by)."""
    mock = AsyncMock(side_effect=[SimpleNamespace(result=r, declined_by=d) for r, d in answers])
    monkeypatch.setattr(main_module, "request_consent", mock)
    return mock


async def _interact(cog: Roleplay, author: _Member, invoker: _Member, target: _Member, passive: bool = False) -> Any:
    ctx: Any = SimpleNamespace(author=author, send=AsyncMock())
    interaction_type = const.InteractionType.PASSIVE if passive else const.InteractionType.ACTIVE
    result = await cog.interaction(ctx, "hug", cast(Any, invoker), cast(Any, target), interaction_type)
    return result, ctx


@pytest.mark.asyncio
async def test_member_is_not_asked_to_consent_to_their_own_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # `&hug` without a target: the bot hugs the member who used it
    bot, author = _Member(1, bot=True), _Member(2)
    cog = _cog({2: {"selective": True}}, {})
    consent = _consent(monkeypatch)

    result, _ = await _interact(cog, author, invoker=bot, target=author)

    assert result is True
    consent.assert_not_awaited()
    cast(AsyncMock, cog.send_action_message).assert_awaited_once()


@pytest.mark.asyncio
async def test_bots_are_not_asked_to_consent(monkeypatch: pytest.MonkeyPatch) -> None:
    # `&ask hug` without a target: the member asks the bot to hug them
    bot, author = _Member(1, bot=True), _Member(2)
    cog = _cog({}, {})
    consent = _consent(monkeypatch)

    result, _ = await _interact(cog, author, invoker=author, target=bot, passive=True)

    assert result is True
    consent.assert_not_awaited()


@pytest.mark.asyncio
async def test_blocked_members_are_told_so(monkeypatch: pytest.MonkeyPatch) -> None:
    author, target = _Member(2), _Member(3)
    cog = _cog({3: {"blocked": [2]}}, {})
    consent = _consent(monkeypatch)

    result, ctx = await _interact(cog, author, invoker=author, target=target)

    assert result is False
    consent.assert_not_awaited()
    assert "can't use that command" in ctx.send.await_args.args[0]


@pytest.mark.asyncio
async def test_selective_member_refuses_members_not_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    author, target = _Member(2), _Member(3)
    cog = _cog({3: {"selective": True}}, {})
    consent = _consent(monkeypatch)

    result, ctx = await _interact(cog, author, invoker=author, target=target)

    assert result is False
    consent.assert_not_awaited()
    assert "does not wish" in ctx.send.await_args.args[0]


@pytest.mark.asyncio
async def test_target_refusal_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    author, target = _Member(2), _Member(3)
    cog = _cog({}, {})
    _consent(monkeypatch, (False, target.id))

    result, ctx = await _interact(cog, author, invoker=author, target=target)

    assert result is False
    assert ctx.send.await_args.args[0] == f"**{target.display_name}** does not wish to do that."
    cast(AsyncMock, cog.send_action_message).assert_not_awaited()


@pytest.mark.asyncio
async def test_unanswered_question_names_who_was_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    author, target = _Member(2), _Member(3)
    author_owner, target_owner = _Member(20), _Member(30)
    cog = _cog({}, {2: author_owner, 3: target_owner})
    _consent(monkeypatch, (None, None))

    result, ctx = await _interact(cog, author, invoker=author, target=target)

    assert result is False
    assert ctx.send.await_args.args[0].startswith("**member20** & **member30** took too long")


@pytest.mark.asyncio
async def test_refusal_names_the_owner_who_declined(monkeypatch: pytest.MonkeyPatch) -> None:
    author, target = _Member(2), _Member(3)
    author_owner, target_owner = _Member(20), _Member(30)
    cog = _cog({}, {2: author_owner, 3: target_owner})
    consent = _consent(monkeypatch, (False, author_owner.id))

    result, ctx = await _interact(cog, author, invoker=author, target=target)

    assert result is False
    assert consent.await_args_list[0].args[2] == [author_owner, target_owner]
    assert ctx.send.await_args.args[0].startswith(author_owner.display_name)


@pytest.mark.asyncio
async def test_target_is_asked_after_the_invokers_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    author, target, author_owner = _Member(2), _Member(3), _Member(20)
    cog = _cog({}, {2: author_owner})
    consent = _consent(monkeypatch, (True, None), (True, None))

    result, _ = await _interact(cog, author, invoker=author, target=target)

    assert result is True
    assert [call.args[2] for call in consent.await_args_list] == [[author_owner], [target]]


def _press(member_id: int) -> Any:
    response = SimpleNamespace(send_message=AsyncMock(), edit_message=AsyncMock())
    return SimpleNamespace(user=SimpleNamespace(id=member_id), response=response)


@pytest.mark.asyncio
async def test_consent_buttons_wait_for_everyone_to_say_yes() -> None:
    view = ConsentView([_Member(10), _Member(20)])  # type: ignore[list-item]

    assert not await view.interaction_check(_press(30))
    await view.yes.callback(_press(10))
    assert view.result is None
    await view.yes.callback(_press(20))
    assert view.result is True
    assert view.is_finished()


@pytest.mark.asyncio
async def test_consent_buttons_stop_on_the_first_no() -> None:
    view = ConsentView([_Member(10), _Member(20)])  # type: ignore[list-item]

    await view.no.callback(_press(20))

    assert view.result is False
    assert view.declined_by == 20
    assert view.is_finished()


@pytest.mark.asyncio
async def test_a_no_is_not_overwritten_by_a_yes_already_queued() -> None:
    # both presses reached the bot before either callback ran
    view = ConsentView([_Member(10), _Member(20)])  # type: ignore[list-item]
    await view.yes.callback(_press(10))

    await view.no.callback(_press(20))
    late_yes = _press(20)
    await view.yes.callback(late_yes)

    assert view.result is False
    assert view.declined_by == 20
    late_yes.response.edit_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_yes_is_not_overwritten_by_a_no_already_queued() -> None:
    view = ConsentView([_Member(10)])  # type: ignore[list-item]

    await view.yes.callback(_press(10))
    await view.no.callback(_press(10))

    assert view.result is True
    assert view.declined_by is None


@pytest.mark.asyncio
async def test_a_press_after_the_question_timed_out_is_ignored() -> None:
    view = ConsentView([_Member(10)])  # type: ignore[list-item]
    view.stop()  # what a timeout does

    await view.yes.callback(_press(10))

    assert view.result is None


def test_actions_are_found_by_alias_in_any_case() -> None:
    manager = ActionManager()

    action = manager.get("HUGS")

    assert action is not None
    assert action.name == "hug"
    assert manager.get("nonsense") is None


def _guild(members: dict[int, _Member]) -> Any:
    fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "Unknown Member"))
    return SimpleNamespace(get_member=members.get, fetch_member=fetch_member)


@pytest.mark.asyncio
async def test_owner_is_found_without_asking_discord() -> None:
    owner = _Member(20)
    ctx: Any = SimpleNamespace(guild=_guild({20: owner}))
    manager = Manager(MagicMock(), MagicMock())

    assert await manager.get_owner(ctx, cast(Any, _Member(2)), [20]) is owner
    ctx.guild.fetch_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_who_left_the_server_is_ignored() -> None:
    ctx: Any = SimpleNamespace(guild=_guild({}))
    manager = Manager(MagicMock(), MagicMock())

    assert await manager.get_owner(ctx, cast(Any, _Member(2)), [20]) is None
    ctx.guild.fetch_member.assert_awaited_once_with(20)


@pytest.mark.asyncio
async def test_display_names_only_fetch_unknown_users() -> None:
    bot = MagicMock()
    bot.get_user = {1: SimpleNamespace(display_name="cached")}.get
    bot.fetch_user = AsyncMock(return_value=SimpleNamespace(display_name="fetched"))
    manager = Manager(bot, MagicMock())

    assert await manager.display_names([1, 2]) == ["cached", "fetched"]
    bot.fetch_user.assert_awaited_once_with(2)


class _Bot(dpy_commands.GroupMixin):
    def __init__(self) -> None:
        super().__init__()


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch) -> _Bot:
    monkeypatch.setattr(settings_module.Config, "get_conf", lambda *_args, **_kwargs: MagicMock())
    return _Bot()


@pytest.mark.asyncio
async def test_cog_can_be_reloaded(bot: _Bot) -> None:
    first = Roleplay(cast(Any, bot))
    await first.cog_unload()
    assert "hug" not in bot.all_commands

    second = Roleplay(cast(Any, bot))

    assert bot.all_commands["hug"] is getattr(second, "hug")  # noqa: B009


@pytest.mark.asyncio
async def test_cog_loads_over_commands_left_by_a_version_without_cleanup(bot: _Bot) -> None:
    Roleplay(cast(Any, bot))

    second = Roleplay(cast(Any, bot))

    assert set(second.action_commands) <= set(bot.all_commands.values())


@pytest.mark.asyncio
async def test_cog_leaves_other_cogs_commands_alone(bot: _Bot) -> None:
    async def hug(ctx: Any) -> None:
        pass

    other = main_module.commands.command(name="hug")(hug)
    bot.add_command(other)

    with pytest.raises(dpy_commands.CommandRegistrationError):
        Roleplay(cast(Any, bot))
    assert bot.all_commands["hug"] is other
