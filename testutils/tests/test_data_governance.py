"""Repository-wide metadata and Config deletion contract tests."""

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest

from customcommand.customcommand import CustomCommand
from tickets.tickets import Tickets

ROOT = Path(__file__).resolve().parents[2]
PERSISTENT_COGS = {
    "antinuke",
    "customcommand",
    "customemoji",
    "customrolecolor",
    "nitroaward",
    "patron",
    "profile",
    "suggest",
    "tickets",
    "unicorn_ai",
    "unicornmoderation",
    "unicornia",
    "unimod",
}


class _Value:
    def __init__(self, data: dict, key: str):
        self.data = data
        self.key = key

    async def set(self, value) -> None:
        self.data[self.key] = value


class _GuildGroup:
    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, key: str) -> _Value:
        return _Value(self._data, key)

    async def all(self) -> dict:
        return copy.deepcopy(self._data)

    async def set(self, value: dict) -> None:
        self._data.clear()
        self._data.update(copy.deepcopy(value))


class _GuildConfig:
    def __init__(self, guilds: dict[int, Any]):
        self.guilds = guilds

    async def all_guilds(self) -> dict[int, Any]:
        return copy.deepcopy(self.guilds)

    def guild_from_id(self, guild_id: int) -> _GuildGroup:
        return _GuildGroup(self.guilds[guild_id])


def test_all_cogs_have_data_statements_and_persistent_cogs_are_truthful() -> None:
    info_files = sorted(ROOT.glob("*/info.json"))
    assert info_files
    for info_file in info_files:
        data = json.loads(info_file.read_text(encoding="utf-8"))
        statement = data.get("end_user_data_statement")
        assert isinstance(statement, str) and statement.strip(), info_file
        if info_file.parent.name in PERSISTENT_COGS:
            lowered = statement.lower()
            assert "does not persistently store" not in lowered, info_file
            source = "\n".join(path.read_text(encoding="utf-8") for path in info_file.parent.glob("*.py"))
            assert "red_delete_data_for_user" in source, info_file


@pytest.mark.asyncio
async def test_customcommand_deletion_removes_owned_content_and_limits() -> None:
    state = {
        1: {
            "commands": {"mine": "private response", "other": "keep"},
            "command_owners": {"42": ["mine"], "99": ["other"]},
            "user_limits": {"42": 5, 42: 7, "99": 2},
        },
        2: None,
    }
    cog = object.__new__(CustomCommand)
    cast(Any, cog).config = _GuildConfig(state)
    cog.command_cache = {}
    cog._guild_locks = {}

    await cog.red_delete_data_for_user(requester="user", user_id=42)

    assert state[1]["commands"] == {"other": "keep"}
    assert state[1]["command_owners"] == {"99": ["other"]}
    assert state[1]["user_limits"] == {"99": 2}


@pytest.mark.asyncio
async def test_ticket_deletion_removes_answers_and_blacklist_id() -> None:
    state = {
        1: {
            "opened": {42: {"100": {"answers": {"name": "private"}}}, "99": {}},
            "blacklist": ["42", 1234],
        }
    }
    cog = object.__new__(Tickets)
    cast(Any, cog).config = _GuildConfig(state)

    await cog.red_delete_data_for_user(requester="user", user_id=42)

    assert 42 not in state[1]["opened"]
    assert state[1]["blacklist"] == [1234]
