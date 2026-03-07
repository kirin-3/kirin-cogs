"""Unit, async, and dpytest integration tests for the CustomCommand cog."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config
from redbot.core.bot import Red

from customcommand.customcommand import CustomCommand

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config_context_manager(backing_dict: dict) -> object:
    """Return an object that supports both ``await obj`` and ``async with obj as d:``.

    Redbot Config's ``async with guild.setting() as s:`` and ``await guild.setting()``
    both call the same object. We create a small class whose type provides
    ``__await__``, ``__aenter__``, and ``__aexit__`` so Python's protocol lookup works.
    """

    async def _aenter(self):
        return backing_dict

    async def _aexit(self, *a):
        return False

    def _await(self):
        async def _coro():
            return backing_dict

        return _coro().__await__()

    DualMock = type(
        "DualMock",
        (),
        {"__aenter__": _aenter, "__aexit__": _aexit, "__await__": _await},
    )
    return DualMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.owner_ids = {111}
    bot.is_owner = AsyncMock(return_value=False)
    bot.get_command = MagicMock(return_value=None)
    bot.get_channel = MagicMock(return_value=None)
    return bot


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)

    guild_group = MagicMock()
    guild_group.commands = AsyncMock(return_value={})
    guild_group.command_owners = AsyncMock(return_value={})
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.command_owners.set_raw = AsyncMock()
    guild_group.command_owners.clear_raw = AsyncMock()
    guild_group.user_limits.set_raw = AsyncMock()

    config.guild = MagicMock(return_value=guild_group)
    config.all_guilds = AsyncMock(return_value={})
    config.register_guild = MagicMock()
    return config


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock, config_mock: MagicMock) -> Any:
    with patch("customcommand.customcommand.Config.get_conf", return_value=config_mock):
        c = CustomCommand(bot_mock)
    c.config = config_mock
    return c


def _make_ctx(
    bot: MagicMock,
    *,
    guild_id: int = 1,
    author_id: int = 500,
    author_roles: list | None = None,
    has_ban_members: bool = False,
    attachments: list | None = None,
) -> Any:
    """Build a minimal Context mock."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id

    author = MagicMock(spec=discord.Member)
    author.id = author_id
    author.roles = author_roles or []
    author.display_name = "TestUser"
    author.avatar = None
    perms = MagicMock(spec=discord.Permissions)
    perms.ban_members = has_ban_members
    author.guild_permissions = perms

    message = MagicMock(spec=discord.Message)
    message.attachments = attachments or []
    message.created_at = discord.utils.utcnow()

    ctx = MagicMock()
    ctx.bot = bot
    ctx.guild = guild
    ctx.author = author
    ctx.message = message
    ctx.send = AsyncMock()
    return ctx


# ---------------------------------------------------------------------------
# cog_load / cog_unload / on_guild_remove
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cog_load_populates_cache(config_mock: MagicMock) -> None:
    config_mock.all_guilds = AsyncMock(
        return_value={
            1: {"commands": {"hello": "world"}},
            2: {"commands": {}},
        }
    )
    bot = MagicMock(spec=Red)
    with patch("customcommand.customcommand.Config.get_conf", return_value=config_mock):
        c = CustomCommand(bot)
    c.config = config_mock

    await c.cog_load()

    assert c.command_cache[1] == {"hello": "world"}
    assert c.command_cache[2] == {}


@pytest.mark.asyncio
async def test_cog_unload_clears_state(cog: Any) -> None:
    cog.command_cache[1] = {"hi": "there"}
    cog.trigger_cooldowns[(1, "hi")] = MagicMock()

    await cog.cog_unload()

    assert cog.command_cache == {}
    assert cog.trigger_cooldowns == {}


@pytest.mark.asyncio
async def test_on_guild_remove_clears_guild_cache(cog: Any) -> None:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 99

    cog.command_cache[99] = {"cmd": "resp"}
    cog.trigger_cooldowns[(99, "cmd")] = MagicMock()
    cog.trigger_cooldowns[(1, "other")] = MagicMock()

    await cog.on_guild_remove(guild)

    assert 99 not in cog.command_cache
    assert (99, "cmd") not in cog.trigger_cooldowns
    # unrelated key preserved
    assert (1, "other") in cog.trigger_cooldowns


# ---------------------------------------------------------------------------
# customcommand_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_limit_rejects_zero(cog: Any, bot_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    member = MagicMock(spec=discord.Member)
    member.display_name = "target"

    await cog.customcommand_limit.callback(cog, ctx, member, 0)

    ctx.send.assert_called_once_with("Limit must be at least 1.")


@pytest.mark.asyncio
async def test_limit_sets_value(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.display_name = "target"

    guild_group = config_mock.guild.return_value
    guild_group.user_limits.set_raw = AsyncMock()

    await cog.customcommand_limit.callback(cog, ctx, member, 5)

    guild_group.user_limits.set_raw.assert_called_once_with("42", value=5)
    ctx.send.assert_called_once_with("Custom command limit for target set to 5.")


# ---------------------------------------------------------------------------
# customcommand_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_no_commands(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={})

    await cog.customcommand_list.callback(cog, ctx)

    ctx.send.assert_called_once_with("No custom commands found.")


@pytest.mark.asyncio
async def test_list_non_mod_no_commands(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=200, has_ban_members=False)
    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={"999": ["other"]})
    guild_group.commands = AsyncMock(return_value={"other": "resp"})

    await cog.customcommand_list.callback(cog, ctx)

    ctx.send.assert_called_once_with("You don't have any custom commands.")


@pytest.mark.asyncio
async def test_list_mod_sees_all(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=1, has_ban_members=True)
    member = MagicMock(spec=discord.Member)
    member.configure_mock(**{"__str__.return_value": "SomeUser"})
    ctx.guild.get_member = MagicMock(return_value=member)

    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={"999": ["hi"]})
    guild_group.commands = AsyncMock(return_value={"hi": "hello there"})

    await cog.customcommand_list.callback(cog, ctx)

    call_args = ctx.send.call_args_list
    assert any("hi" in str(c) for c in call_args)


@pytest.mark.asyncio
async def test_list_non_mod_sees_own_commands(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, has_ban_members=False)
    member = MagicMock(spec=discord.Member)
    member.configure_mock(**{"__str__.return_value": "Me"})
    ctx.guild.get_member = MagicMock(return_value=member)

    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={"500": ["mycommand"]})
    guild_group.commands = AsyncMock(return_value={"mycommand": "my response"})

    await cog.customcommand_list.callback(cog, ctx)

    call_args = ctx.send.call_args_list
    assert any("mycommand" in str(c) for c in call_args)


# ---------------------------------------------------------------------------
# customcommand_create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_requires_role(cog: Any, bot_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)  # no roles
    await cog.customcommand_create.callback(cog, ctx, "hello", "world")
    ctx.send.assert_called_once_with("You don't have the required role to create a custom command.")


@pytest.mark.asyncio
async def test_create_requires_response(cog: Any, bot_mock: MagicMock) -> None:
    role = MagicMock(spec=discord.Role)
    role.id = cog.role_id
    ctx = _make_ctx(bot_mock, author_roles=[role])

    await cog.customcommand_create.callback(cog, ctx, "hello", None)
    ctx.send.assert_called_once_with("Please provide a response or attach an image.")


@pytest.mark.asyncio
async def test_create_rejects_bot_prefix_response(cog: Any, bot_mock: MagicMock) -> None:
    role = MagicMock(spec=discord.Role)
    role.id = cog.role_id
    ctx = _make_ctx(bot_mock, author_roles=[role])

    await cog.customcommand_create.callback(cog, ctx, "hello", ".bad response")
    ctx.send.assert_called_once_with("Responses cannot start with '.', '-', or '&' to prevent bot conflicts.")


@pytest.mark.asyncio
async def test_create_rejects_non_alphanumeric_trigger(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    role = MagicMock(spec=discord.Role)
    role.id = cog.role_id
    ctx = _make_ctx(bot_mock, author_roles=[role])

    guild_group = config_mock.guild.return_value
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.command_owners = AsyncMock(return_value={})

    await cog.customcommand_create.callback(cog, ctx, "hello!", "valid response")
    ctx.send.assert_called_once_with("Trigger must be alphanumeric (spaces are allowed).")


@pytest.mark.asyncio
async def test_create_rejects_existing_bot_command(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    role = MagicMock(spec=discord.Role)
    role.id = cog.role_id
    ctx = _make_ctx(bot_mock, author_roles=[role])
    bot_mock.get_command = MagicMock(return_value=MagicMock())

    guild_group = config_mock.guild.return_value
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.command_owners = AsyncMock(return_value={})

    await cog.customcommand_create.callback(cog, ctx, "ping", "pong")
    ctx.send.assert_called_once_with("A command with this name already exists.")


@pytest.mark.asyncio
async def test_create_rejects_existing_custom_command(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    role = MagicMock(spec=discord.Role)
    role.id = cog.role_id
    ctx = _make_ctx(bot_mock, author_roles=[role])

    guild_group = config_mock.guild.return_value
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.command_owners = AsyncMock(return_value={})
    guild_group.commands = AsyncMock(return_value={"hello": "already exists"})

    await cog.customcommand_create.callback(cog, ctx, "hello", "world")
    ctx.send.assert_called_once_with("A custom command with this trigger already exists.")


@pytest.mark.asyncio
async def test_create_enforces_user_limit(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    role = MagicMock(spec=discord.Role)
    role.id = cog.role_id
    ctx = _make_ctx(bot_mock, author_id=500, author_roles=[role])
    bot_mock.is_owner = AsyncMock(return_value=False)

    guild_group = config_mock.guild.return_value
    guild_group.user_limits = AsyncMock(return_value={"500": 1})
    guild_group.command_owners = AsyncMock(return_value={"500": ["existing"]})
    guild_group.commands = AsyncMock(return_value={})

    await cog.customcommand_create.callback(cog, ctx, "newcmd", "response")
    ctx.send.assert_called_once_with("You have reached your limit of 1 custom command(s).")


@pytest.mark.asyncio
async def test_create_success(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    role = MagicMock(spec=discord.Role)
    role.id = cog.role_id
    ctx = _make_ctx(bot_mock, author_id=500, author_roles=[role], guild_id=1)

    guild_group = config_mock.guild.return_value
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.command_owners = AsyncMock(return_value={})
    guild_group.command_owners.set_raw = AsyncMock()

    # commands() must support both `await` (returns {}) and `async with ... as c:` (yields {}).
    commands_dict: dict = {}
    guild_group.commands = MagicMock(return_value=_make_config_context_manager(commands_dict))

    cog.log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.customcommand_create.callback(cog, ctx, "hello", "world")

    ctx.send.assert_called_once_with("Custom command `hello` has been created.")
    assert cog.command_cache[1]["hello"] == "world"


@pytest.mark.asyncio
async def test_create_with_attachment(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    role = MagicMock(spec=discord.Role)
    role.id = cog.role_id

    attachment = MagicMock(spec=discord.Attachment)
    attachment.url = "https://cdn.discord.com/image.png"

    ctx = _make_ctx(bot_mock, author_id=500, author_roles=[role], guild_id=1, attachments=[attachment])

    guild_group = config_mock.guild.return_value
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.command_owners = AsyncMock(return_value={})
    guild_group.command_owners.set_raw = AsyncMock()

    commands_dict: dict = {}
    guild_group.commands = MagicMock(return_value=_make_config_context_manager(commands_dict))

    cog.log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.customcommand_create.callback(cog, ctx, "img", None)

    ctx.send.assert_called_once_with("Custom command `img` has been created.")
    assert cog.command_cache[1]["img"] == attachment.url


# ---------------------------------------------------------------------------
# customcommand_delete — regular user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_no_commands_for_user(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, has_ban_members=False)
    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={})

    await cog.customcommand_delete.callback(cog, ctx, "hello")
    ctx.send.assert_called_once_with("You don't have a custom command to delete.")


@pytest.mark.asyncio
async def test_delete_trigger_not_owned(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, has_ban_members=False)
    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={"500": ["othercmd"]})

    await cog.customcommand_delete.callback(cog, ctx, "hello")
    ctx.send.assert_called_once_with("You don't own a command with that name.")


@pytest.mark.asyncio
async def test_delete_multiple_commands_no_trigger(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, has_ban_members=False)
    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={"500": ["cmd1", "cmd2"]})

    await cog.customcommand_delete.callback(cog, ctx, None)
    ctx.send.assert_called_once()
    assert "multiple commands" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_delete_user_success(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, guild_id=1, has_ban_members=False)
    cog.command_cache[1] = {"hello": "world"}

    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={"500": ["hello"]})
    guild_group.command_owners.set_raw = AsyncMock()
    guild_group.command_owners.clear_raw = AsyncMock()

    commands_dict: dict = {"hello": "world"}
    commands_cm = MagicMock()
    commands_cm.__aenter__ = AsyncMock(return_value=commands_dict)
    commands_cm.__aexit__ = AsyncMock(return_value=False)
    guild_group.commands = MagicMock(return_value=commands_cm)

    cog.log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.customcommand_delete.callback(cog, ctx, "hello")

    ctx.send.assert_called_once_with("Your custom command `hello` has been deleted.")
    assert "hello" not in cog.command_cache.get(1, {})


# ---------------------------------------------------------------------------
# customcommand_delete — mod
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_mod_not_found(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=1, guild_id=1, has_ban_members=True)
    cog.command_cache[1] = {}

    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={})

    await cog.customcommand_delete.callback(cog, ctx, "missing")
    ctx.send.assert_called_once_with("Command not found.")


@pytest.mark.asyncio
async def test_delete_mod_success(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=1, guild_id=1, has_ban_members=True)
    cog.command_cache[1] = {"hello": "world"}

    guild_group = config_mock.guild.return_value
    guild_group.command_owners = AsyncMock(return_value={"500": ["hello"]})
    guild_group.command_owners.set_raw = AsyncMock()
    guild_group.command_owners.clear_raw = AsyncMock()

    commands_dict: dict = {"hello": "world"}
    commands_cm = MagicMock()
    commands_cm.__aenter__ = AsyncMock(return_value=commands_dict)
    commands_cm.__aexit__ = AsyncMock(return_value=False)
    guild_group.commands = MagicMock(return_value=commands_cm)

    cog.log_action = AsyncMock()  # type: ignore[method-assign]

    await cog.customcommand_delete.callback(cog, ctx, "hello")

    ctx.send.assert_called_once_with("Custom command `hello` has been deleted by moderator.")
    assert "hello" not in cog.command_cache.get(1, {})


# ---------------------------------------------------------------------------
# on_message_without_command — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_message_ignores_bots(cog: Any) -> None:
    message = MagicMock(spec=discord.Message)
    message.author = MagicMock()
    message.author.bot = True
    message.guild = MagicMock()
    message.channel = MagicMock()

    await cog.on_message_without_command(message)
    message.channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_ignores_dm(cog: Any) -> None:
    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.guild = None
    message.channel = MagicMock()

    await cog.on_message_without_command(message)
    message.channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_unknown_trigger(cog: Any) -> None:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    cog.command_cache[1] = {"hello": "world"}

    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.guild = guild
    message.content = "goodbye"
    message.channel = MagicMock()
    message.channel.send = AsyncMock()

    await cog.on_message_without_command(message)
    message.channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_on_message_sends_response(cog: Any) -> None:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    cog.command_cache[1] = {"hello": "world"}

    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.guild = guild
    message.content = "hello"
    message.channel = MagicMock()
    message.channel.send = AsyncMock()
    message.channel.id = 10

    await cog.on_message_without_command(message)
    message.channel.send.assert_called_once_with("world")


@pytest.mark.asyncio
async def test_on_message_respects_cooldown(cog: Any) -> None:
    """Second identical trigger within the cooldown window is suppressed."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 1
    cog.command_cache[1] = {"hello": "world"}

    def _make_message():
        message = MagicMock(spec=discord.Message)
        message.author.bot = False
        message.guild = guild
        message.content = "hello"
        message.channel = MagicMock()
        message.channel.send = AsyncMock()
        message.channel.id = 10
        return message

    msg1 = _make_message()
    msg2 = _make_message()

    await cog.on_message_without_command(msg1)
    await cog.on_message_without_command(msg2)

    msg1.channel.send.assert_called_once_with("world")
    msg2.channel.send.assert_not_called()


# ---------------------------------------------------------------------------
# log_action — channel not found (silent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_action_silent_when_channel_missing(cog: Any, bot_mock: MagicMock) -> None:
    bot_mock.get_channel.return_value = None
    ctx = _make_ctx(bot_mock)

    # Should not raise
    await cog.log_action(ctx, "Created", "hello", "world")


# ---------------------------------------------------------------------------
# dpytest integration — on_message_without_command dispatched via real event
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def dpytest_bot() -> AsyncGenerator[dpy_commands.Bot, None]:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True
    intents.messages = True
    intents.message_content = True

    bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(bot)

    yield bot

    await dpytest.empty_queue()


@pytest.mark.asyncio
async def test_dpytest_trigger_fires_response(dpytest_bot: dpy_commands.Bot) -> None:
    """Dispatching on_message_without_command for a known trigger sends the response.

    ``on_message_without_command`` is a Redbot-specific event that plain discord.py
    doesn't dispatch, so we dispatch it manually via bot.dispatch().
    """
    config_mock = MagicMock(spec=Config)
    config_mock.all_guilds = AsyncMock(return_value={})
    config_mock.register_guild = MagicMock()

    with patch("customcommand.customcommand.Config.get_conf", return_value=config_mock):
        cog = CustomCommand(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock

    guild = dpytest.get_config().guilds[0]
    dpytest.get_config().channels[0]
    cog.command_cache[guild.id] = {"hi": "hello!"}

    await dpytest_bot.add_cog(cog)

    # Build a realistic message and dispatch the Redbot-specific event directly.
    author = MagicMock()
    author.bot = False
    channel_mock = MagicMock()
    channel_mock.send = AsyncMock()
    channel_mock.id = dpytest.get_config().channels[0].id

    message = MagicMock(spec=discord.Message)
    message.author = author
    message.guild = guild
    message.content = "hi"
    message.channel = channel_mock

    dpytest_bot.dispatch("message_without_command", message)
    await dpytest.run_all_events()

    pending = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    channel_mock.send.assert_called_once_with("hello!")


@pytest.mark.asyncio
async def test_dpytest_unknown_trigger_no_response(dpytest_bot: dpy_commands.Bot) -> None:
    """Dispatching an unknown trigger via on_message_without_command sends nothing."""
    config_mock = MagicMock(spec=Config)
    config_mock.all_guilds = AsyncMock(return_value={})
    config_mock.register_guild = MagicMock()

    with patch("customcommand.customcommand.Config.get_conf", return_value=config_mock):
        cog = CustomCommand(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock

    guild = dpytest.get_config().guilds[0]
    dpytest.get_config().channels[0]
    cog.command_cache[guild.id] = {"hi": "hello!"}

    await dpytest_bot.add_cog(cog)

    author = MagicMock()
    author.bot = False
    channel_mock = MagicMock()
    channel_mock.send = AsyncMock()
    channel_mock.id = dpytest.get_config().channels[0].id

    message = MagicMock(spec=discord.Message)
    message.author = author
    message.guild = guild
    message.content = "unknown trigger"
    message.channel = channel_mock

    dpytest_bot.dispatch("message_without_command", message)
    await dpytest.run_all_events()

    pending = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    channel_mock.send.assert_not_called()
