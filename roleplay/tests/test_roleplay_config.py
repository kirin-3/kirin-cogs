"""Guards the Config storage key that existing members' roleplay settings live under,
plus the data-deletion and consent-reply logic."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from roleplay import settings as settings_module
from roleplay.unicornia.predicates import ExtendedMessagePredicate
from roleplay.users import Manager


def test_config_storage_key_matches_existing_data(monkeypatch: pytest.MonkeyPatch) -> None:
    config = MagicMock()
    calls: list[dict[str, Any]] = []

    def get_conf(_cog_instance: object, **kwargs: Any) -> MagicMock:
        calls.append(kwargs)
        return config

    monkeypatch.setattr(settings_module.Config, "get_conf", get_conf)
    settings_module.Settings(bot=MagicMock(), parent=MagicMock())

    assert calls == [{"identifier": 842364413, "force_registration": True, "cog_name": "Settings"}]
    config.register_user.assert_called_once_with(
        owners=[], allowed=[], blocked=[], selective=False, public=False, servant=False
    )


class _UserConfig:
    def __init__(self, users: dict[int, dict[str, Any]]) -> None:
        self.users = users

    async def all_users(self) -> dict[int, dict[str, Any]]:
        return {user_id: dict(data) for user_id, data in self.users.items()}

    def user_from_id(self, user_id: int) -> SimpleNamespace:
        async def clear() -> None:
            self.users.pop(user_id, None)

        def get_attr(key: str) -> SimpleNamespace:
            async def set_value(value: Any) -> None:
                self.users[user_id][key] = value

            return SimpleNamespace(set=set_value)

        return SimpleNamespace(clear=clear, get_attr=get_attr)


@pytest.mark.asyncio
async def test_delete_user_data_removes_own_settings_and_references() -> None:
    users: dict[int, dict[str, Any]] = {
        42: {"owners": [7], "public": True},
        7: {"allowed": [42, 8], "blocked": [42], "owners": None},
        8: {"allowed": [7]},
    }
    manager = Manager(MagicMock(), cast(Any, _UserConfig(users)))

    await manager.delete_user_data(42)

    assert users == {7: {"allowed": [8], "blocked": [], "owners": None}, 8: {"allowed": [7]}}


def _message(author_id: int, content: str, channel_id: int = 1) -> Any:
    return SimpleNamespace(
        author=SimpleNamespace(id=author_id), channel=SimpleNamespace(id=channel_id), content=content
    )


def test_yes_or_no_waits_for_every_user_to_agree() -> None:
    pred = ExtendedMessagePredicate(channel_id=1, user_ids={10, 20})

    assert not pred(_message(10, "yes", channel_id=2))
    assert not pred(_message(30, "yes"))
    assert not pred(_message(10, "Yes"))
    assert pred.result is None
    assert pred(_message(20, "sure"))
    assert pred.result is True


def test_yes_or_no_stops_on_first_no() -> None:
    pred = ExtendedMessagePredicate(channel_id=1, user_ids={10, 20})

    assert not pred(_message(10, "maybe"))
    assert pred(_message(20, "nope"))
    assert pred.result is False
