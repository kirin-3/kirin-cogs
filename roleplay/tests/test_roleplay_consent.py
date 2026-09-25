"""Covers who gets asked for consent, the consent buttons, action lookup, image
downloads and reloading the cog."""

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import requests
from discord.ext import commands as dpy_commands

from roleplay import const
from roleplay import main as main_module
from roleplay import settings as settings_module
from roleplay.actions import ActionManager
from roleplay.main import Roleplay
from roleplay.unicornia import web
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
        values = settings.get(member.id, {})
        return SimpleNamespace(
            **{flag: AsyncMock(return_value=values.get(flag, False)) for flag in ("public", "servant", "selective")}
        )

    async def in_group(member: _Member, user_or_id: Any, group: str) -> bool:
        user_id = user_or_id if isinstance(user_or_id, int) else user_or_id.id
        return user_id in settings.get(member.id, {}).get(group, [])

    async def get_owner(_ctx: Any, member: _Member) -> _Member | None:
        return owners.get(member.id)

    cog = Roleplay.__new__(Roleplay)
    cog.bot = MagicMock()
    cog.logger = logging.getLogger("test_roleplay")
    cog.action_manager = ActionManager()
    cog.user_settings = cast(
        Any,
        SimpleNamespace(
            config=SimpleNamespace(user=user),
            users_manager=SimpleNamespace(in_group=in_group, get_owner=get_owner),
        ),
    )
    cog.send_action_message = AsyncMock()
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
async def test_selective_member_refuses_members_not_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    author, target = _Member(2), _Member(3)
    cog = _cog({3: {"selective": True}}, {})
    consent = _consent(monkeypatch)

    result, ctx = await _interact(cog, author, invoker=author, target=target)

    assert result is False
    consent.assert_not_awaited()
    assert "does not wish" in ctx.send.await_args.args[0]


@pytest.mark.asyncio
async def test_selective_member_still_accepts_allowed_members(monkeypatch: pytest.MonkeyPatch) -> None:
    author, target = _Member(2), _Member(3)
    cog = _cog({3: {"selective": True, "allowed": [2]}}, {})
    _consent(monkeypatch)

    result, _ = await _interact(cog, author, invoker=author, target=target)

    assert result is True


@pytest.mark.asyncio
async def test_selective_public_member_accepts_active_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    author, target = _Member(2), _Member(3)
    cog = _cog({3: {"selective": True, "public": True}}, {})
    consent = _consent(monkeypatch)

    result, _ = await _interact(cog, author, invoker=author, target=target)

    assert result is True
    consent.assert_not_awaited()


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


def test_actions_are_found_by_alias_in_any_case() -> None:
    manager = ActionManager()

    action = manager.get("HUGS")

    assert action is not None
    assert action.name == "hug"
    assert manager.get("nonsense") is None


def test_download_skips_images_already_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    get = MagicMock(return_value=SimpleNamespace(content=b"gif", raise_for_status=lambda: None))
    monkeypatch.setattr(web.requests, "get", get)

    assert web.save_image_from_url("https://a.example/x/tenor.gif", tmp_path, "hug") is True
    assert web.save_image_from_url("https://a.example/x/tenor.gif", tmp_path, "hug") is False
    # a different URL with the same file name is saved separately
    assert web.save_image_from_url("https://a.example/y/tenor.gif", tmp_path, "hug") is True
    assert get.call_count == 2
    assert len(list((tmp_path / "hug").iterdir())) == 2


def test_download_reports_connection_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web.requests, "get", MagicMock(side_effect=requests.ConnectionError))

    assert web.save_image_from_url("https://a.example/hug.gif", tmp_path, "hug") is None


class _Bot(dpy_commands.GroupMixin):
    def __init__(self) -> None:
        super().__init__()
        self.loop = SimpleNamespace(create_task=lambda coro: coro.close())


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
