"""Unit, async, and dpytest integration tests for the CustomEmoji cog."""

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

from customemoji.customemoji import CustomEmoji


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _acm(backing_dict: dict) -> object:
    """Async context manager that also supports ``await obj`` — mirrors Redbot Config."""

    async def _aenter(self):
        return backing_dict

    async def _aexit(self, *a):
        return False

    def _await(self):
        async def _coro():
            return backing_dict

        return _coro().__await__()

    DualMock = type("DualMock", (), {"__aenter__": _aenter, "__aexit__": _aexit, "__await__": _await})
    return DualMock()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bot_mock() -> MagicMock:
    # Don't use spec=Red here so we can set arbitrary attributes like .session
    bot = MagicMock()
    bot.owner_ids = {111}
    bot.is_mod = AsyncMock(return_value=False)
    return bot


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)

    guild_group = MagicMock()
    guild_group.required_role_id = AsyncMock(return_value=None)
    guild_group.required_role_id.set = AsyncMock()
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.emoji_ownership = AsyncMock(return_value={})

    config.guild = MagicMock(return_value=guild_group)
    config.register_guild = MagicMock()
    return config


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock, config_mock: MagicMock) -> Any:
    with patch("customemoji.customemoji.Config.get_conf", return_value=config_mock):
        c = CustomEmoji(bot_mock)
    c.config = config_mock
    return c


def _make_ctx(
    bot: MagicMock,
    *,
    guild_id: int = 1,
    author_id: int = 500,
    author_roles: list | None = None,
    is_mod: bool = False,
    manage_emojis: bool = False,
    attachments: list | None = None,
) -> Any:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.features = []

    author = MagicMock(spec=discord.Member)
    author.id = author_id
    author.roles = author_roles or []
    author.display_name = "TestUser"
    perms = MagicMock(spec=discord.Permissions)
    perms.manage_emojis = manage_emojis
    author.guild_permissions = perms

    message = MagicMock(spec=discord.Message)
    message.attachments = attachments or []

    ctx = MagicMock()
    ctx.bot = bot
    ctx.guild = guild
    ctx.author = author
    ctx.message = message
    ctx.send = AsyncMock()
    return ctx


# ---------------------------------------------------------------------------
# Helper methods — no command decorator, call directly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_limit_default(cog: Any, config_mock: MagicMock) -> None:
    guild = MagicMock(spec=discord.Guild)
    config_mock.guild.return_value.user_limits = AsyncMock(return_value={})

    result = await cog.get_user_limit(guild, 42)
    assert result == 2


@pytest.mark.asyncio
async def test_get_user_limit_custom(cog: Any, config_mock: MagicMock) -> None:
    guild = MagicMock(spec=discord.Guild)
    config_mock.guild.return_value.user_limits = AsyncMock(return_value={"42": 5})

    result = await cog.get_user_limit(guild, 42)
    assert result == 5


@pytest.mark.asyncio
async def test_get_user_emoji_count(cog: Any, config_mock: MagicMock) -> None:
    guild = MagicMock(spec=discord.Guild)
    config_mock.guild.return_value.emoji_ownership = AsyncMock(return_value={"1001": 42, "1002": 99, "1003": 42})

    result = await cog.get_user_emoji_count(guild, 42)
    assert result == 2


@pytest.mark.asyncio
async def test_download_image_too_large(cog: Any, bot_mock: MagicMock) -> None:
    response_mock = MagicMock()
    response_mock.status = 200
    response_mock.read = AsyncMock(return_value=b"x" * (257 * 1024))
    response_mock.__aenter__ = AsyncMock(return_value=response_mock)
    response_mock.__aexit__ = AsyncMock(return_value=False)
    bot_mock.session.get = MagicMock(return_value=response_mock)

    with pytest.raises(ValueError, match="too large"):
        await cog.download_image("https://example.com/image.png")


@pytest.mark.asyncio
async def test_download_image_non_200(cog: Any, bot_mock: MagicMock) -> None:
    response_mock = MagicMock()
    response_mock.status = 404
    response_mock.__aenter__ = AsyncMock(return_value=response_mock)
    response_mock.__aexit__ = AsyncMock(return_value=False)
    bot_mock.session.get = MagicMock(return_value=response_mock)

    with pytest.raises(ValueError, match="Failed to download"):
        await cog.download_image("https://example.com/image.png")


# ---------------------------------------------------------------------------
# ce_setrole
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setrole_with_role(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    role = MagicMock(spec=discord.Role)
    role.id = 999
    role.name = "MyRole"

    guild_group = config_mock.guild.return_value
    guild_group.required_role_id.set = AsyncMock()

    await cog.ce_setrole.callback(cog, ctx, role)

    guild_group.required_role_id.set.assert_called_once_with(999)
    ctx.send.assert_called_once_with("Required role set to MyRole.")


@pytest.mark.asyncio
async def test_setrole_clear(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    guild_group = config_mock.guild.return_value
    guild_group.required_role_id.set = AsyncMock()

    await cog.ce_setrole.callback(cog, ctx, None)

    guild_group.required_role_id.set.assert_called_once_with(None)
    ctx.send.assert_called_once()
    assert "removed" in ctx.send.call_args[0][0]


# ---------------------------------------------------------------------------
# ce_limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_limit_negative(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.display_name = "target"

    await cog.ce_limit.callback(cog, ctx, member, -1)
    ctx.send.assert_called_once_with("Limit cannot be negative.")


@pytest.mark.asyncio
async def test_limit_zero_allowed(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.display_name = "target"

    limits_dict: dict = {}
    config_mock.guild.return_value.user_limits = MagicMock(return_value=_acm(limits_dict))

    await cog.ce_limit.callback(cog, ctx, member, 0)

    assert limits_dict["42"] == 0
    ctx.send.assert_called_once_with("Set emoji limit for target to 0.")


# ---------------------------------------------------------------------------
# ce_resetlimit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resetlimit_has_custom(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.display_name = "target"

    limits_dict: dict = {"42": 5}
    config_mock.guild.return_value.user_limits = MagicMock(return_value=_acm(limits_dict))

    await cog.ce_resetlimit.callback(cog, ctx, member)

    assert "42" not in limits_dict
    ctx.send.assert_called_once()
    assert "Reset" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_resetlimit_no_custom(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.display_name = "target"

    limits_dict: dict = {}
    config_mock.guild.return_value.user_limits = MagicMock(return_value=_acm(limits_dict))

    await cog.ce_resetlimit.callback(cog, ctx, member)
    ctx.send.assert_called_once()
    assert "does not have a custom limit" in ctx.send.call_args[0][0]


# ---------------------------------------------------------------------------
# ce_create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_requires_role_when_set(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)

    required_role = MagicMock(spec=discord.Role)
    required_role.id = 888
    ctx.guild.get_role = MagicMock(return_value=required_role)

    guild_group = config_mock.guild.return_value
    guild_group.required_role_id = AsyncMock(return_value=888)

    await cog.ce_create.callback(cog, ctx, "myemoji", None)
    ctx.send.assert_called_once_with("You do not have the required role to create emojis.")


@pytest.mark.asyncio
async def test_create_role_no_longer_exists(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    ctx.guild.get_role = MagicMock(return_value=None)

    guild_group = config_mock.guild.return_value
    guild_group.required_role_id = AsyncMock(return_value=888)

    await cog.ce_create.callback(cog, ctx, "myemoji", None)
    ctx.send.assert_called_once()
    assert "no longer exists" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_create_at_limit(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)

    guild_group = config_mock.guild.return_value
    guild_group.required_role_id = AsyncMock(return_value=None)
    guild_group.user_limits = AsyncMock(return_value={"500": 1})
    guild_group.emoji_ownership = AsyncMock(return_value={"1001": 500})

    await cog.ce_create.callback(cog, ctx, "myemoji", None)
    ctx.send.assert_called_once_with("You have reached your limit of 1 emojis.")


@pytest.mark.asyncio
async def test_create_no_source_no_attachment(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)

    guild_group = config_mock.guild.return_value
    guild_group.required_role_id = AsyncMock(return_value=None)
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.emoji_ownership = AsyncMock(return_value={})

    await cog.ce_create.callback(cog, ctx, "myemoji", None)
    ctx.send.assert_called_once_with("Please provide an image attachment or a valid emoji/URL.")


@pytest.mark.asyncio
async def test_create_invalid_attachment_type(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    attachment = MagicMock(spec=discord.Attachment)
    attachment.filename = "file.txt"
    attachment.size = 1024

    ctx = _make_ctx(bot_mock, author_id=500, attachments=[attachment])

    guild_group = config_mock.guild.return_value
    guild_group.required_role_id = AsyncMock(return_value=None)
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.emoji_ownership = AsyncMock(return_value={})

    await cog.ce_create.callback(cog, ctx, "myemoji", None)
    ctx.send.assert_called_once_with("Invalid file type. Please upload a PNG, JPG, or GIF.")


@pytest.mark.asyncio
async def test_create_attachment_too_large(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    attachment = MagicMock(spec=discord.Attachment)
    attachment.filename = "image.png"
    attachment.size = 300 * 1024

    ctx = _make_ctx(bot_mock, author_id=500, attachments=[attachment])

    guild_group = config_mock.guild.return_value
    guild_group.required_role_id = AsyncMock(return_value=None)
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.emoji_ownership = AsyncMock(return_value={})

    await cog.ce_create.callback(cog, ctx, "myemoji", None)
    ctx.send.assert_called_once_with("Image is too large (max 256KB).")


@pytest.mark.asyncio
async def test_create_success_with_attachment(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    image_bytes = b"fakepngdata"
    attachment = MagicMock(spec=discord.Attachment)
    attachment.filename = "image.png"
    attachment.size = 1024
    attachment.read = AsyncMock(return_value=image_bytes)

    ctx = _make_ctx(bot_mock, author_id=500, attachments=[attachment])

    fake_emoji = MagicMock(spec=discord.Emoji)
    fake_emoji.id = 1001
    fake_emoji.name = "myemoji"
    fake_emoji.configure_mock(**{"__str__.return_value": "<:myemoji:1001>"})
    ctx.guild.create_custom_emoji = AsyncMock(return_value=fake_emoji)

    guild_group = config_mock.guild.return_value
    guild_group.required_role_id = AsyncMock(return_value=None)
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.emoji_ownership = AsyncMock(return_value={})

    ownership_dict: dict = {}
    guild_group.emoji_ownership = MagicMock(return_value=_acm(ownership_dict))

    await cog.ce_create.callback(cog, ctx, "myemoji", None)

    ctx.guild.create_custom_emoji.assert_called_once()
    assert ownership_dict["1001"] == 500
    ctx.send.assert_called_once()
    assert "created successfully" in ctx.send.call_args[0][0]


# ---------------------------------------------------------------------------
# ce_delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_not_owner_not_mod(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    bot_mock.is_mod = AsyncMock(return_value=False)

    emoji = MagicMock(spec=discord.Emoji)
    emoji.id = 1001
    emoji.name = "myemoji"

    guild_group = config_mock.guild.return_value
    guild_group.emoji_ownership = AsyncMock(return_value={"1001": 999})

    await cog.ce_delete.callback(cog, ctx, emoji)
    ctx.send.assert_called_once_with("You do not own this emoji and do not have permission to delete it.")


@pytest.mark.asyncio
async def test_delete_owner_success(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    bot_mock.is_mod = AsyncMock(return_value=False)

    emoji = MagicMock(spec=discord.Emoji)
    emoji.id = 1001
    emoji.name = "myemoji"
    emoji.delete = AsyncMock()

    guild_group = config_mock.guild.return_value
    guild_group.emoji_ownership = AsyncMock(return_value={"1001": 500})

    ownership_dict: dict = {"1001": 500}
    guild_group.emoji_ownership = MagicMock(return_value=_acm(ownership_dict))

    await cog.ce_delete.callback(cog, ctx, emoji)

    emoji.delete.assert_called_once()
    assert "1001" not in ownership_dict
    ctx.send.assert_called_once_with("Emoji `myemoji` has been deleted.")


@pytest.mark.asyncio
async def test_delete_mod_can_delete_others_emoji(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=1, manage_emojis=True)
    bot_mock.is_mod = AsyncMock(return_value=True)

    emoji = MagicMock(spec=discord.Emoji)
    emoji.id = 1001
    emoji.name = "someemoji"
    emoji.delete = AsyncMock()

    ownership_dict: dict = {"1001": 999}
    config_mock.guild.return_value.emoji_ownership = MagicMock(return_value=_acm(ownership_dict))

    await cog.ce_delete.callback(cog, ctx, emoji)

    emoji.delete.assert_called_once()
    ctx.send.assert_called_once_with("Emoji `someemoji` has been deleted.")


@pytest.mark.asyncio
async def test_delete_forbidden(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    bot_mock.is_mod = AsyncMock(return_value=False)

    emoji = MagicMock(spec=discord.Emoji)
    emoji.id = 1001
    emoji.name = "myemoji"
    emoji.delete = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perm"))

    ownership_dict: dict = {"1001": 500}
    config_mock.guild.return_value.emoji_ownership = MagicMock(return_value=_acm(ownership_dict))

    await cog.ce_delete.callback(cog, ctx, emoji)
    ctx.send.assert_called_once_with("I do not have permission to delete this emoji.")


# ---------------------------------------------------------------------------
# ce_rename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_invalid_name(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)

    emoji = MagicMock(spec=discord.Emoji)
    emoji.id = 1001

    guild_group = config_mock.guild.return_value
    guild_group.emoji_ownership = AsyncMock(return_value={"1001": 500})

    await cog.ce_rename.callback(cog, ctx, emoji, "bad name!")
    ctx.send.assert_called_once()
    assert "alphanumeric" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_rename_not_owner(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)

    emoji = MagicMock(spec=discord.Emoji)
    emoji.id = 1001

    guild_group = config_mock.guild.return_value
    guild_group.emoji_ownership = AsyncMock(return_value={"1001": 999})

    await cog.ce_rename.callback(cog, ctx, emoji, "newname")
    ctx.send.assert_called_once_with("You do not own this emoji.")


@pytest.mark.asyncio
async def test_rename_success(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)

    emoji = MagicMock(spec=discord.Emoji)
    emoji.id = 1001
    emoji.edit = AsyncMock()

    guild_group = config_mock.guild.return_value
    guild_group.emoji_ownership = AsyncMock(return_value={"1001": 500})

    await cog.ce_rename.callback(cog, ctx, emoji, "coolname")

    emoji.edit.assert_called_once()
    ctx.send.assert_called_once_with("Emoji renamed to `:coolname:`.")


# ---------------------------------------------------------------------------
# ce_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_self_no_emojis(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)

    guild_group = config_mock.guild.return_value
    guild_group.emoji_ownership = AsyncMock(return_value={})
    guild_group.user_limits = AsyncMock(return_value={})

    await cog.ce_list.callback(cog, ctx, None)
    ctx.send.assert_called_once()
    assert "no custom emojis" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_list_other_user_non_mod_rejected(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    bot_mock.is_mod = AsyncMock(return_value=False)

    other_user = MagicMock(spec=discord.Member)
    other_user.id = 999

    await cog.ce_list.callback(cog, ctx, other_user)
    ctx.send.assert_called_once_with("You can only view your own emojis.")


@pytest.mark.asyncio
async def test_list_mod_can_view_other(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=1)
    bot_mock.is_mod = AsyncMock(return_value=True)

    other_user = MagicMock(spec=discord.Member)
    other_user.id = 999
    other_user.display_name = "SomeUser"

    guild_group = config_mock.guild.return_value
    guild_group.emoji_ownership = AsyncMock(return_value={"1001": 999})
    guild_group.user_limits = AsyncMock(return_value={})

    fake_emoji = MagicMock(spec=discord.Emoji)
    fake_emoji.id = 1001
    fake_emoji.name = "cool"
    fake_emoji.configure_mock(**{"__str__.return_value": "<:cool:1001>"})
    ctx.guild.get_emoji = MagicMock(return_value=fake_emoji)

    await cog.ce_list.callback(cog, ctx, other_user)

    ctx.send.assert_called_once()
    _, kwargs = ctx.send.call_args
    assert "embed" in kwargs


@pytest.mark.asyncio
async def test_list_cleans_up_stale_emojis(cog: Any, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    """Stale emoji IDs (deleted from guild) are cleaned up and user is notified."""
    ctx = _make_ctx(bot_mock, author_id=500)

    ownership_dict: dict = {"9999": 500}
    guild_group = config_mock.guild.return_value
    guild_group.emoji_ownership = AsyncMock(return_value={"9999": 500})
    guild_group.user_limits = AsyncMock(return_value={})

    ctx.guild.get_emoji = MagicMock(return_value=None)

    guild_group.emoji_ownership = MagicMock(return_value=_acm(ownership_dict))

    await cog.ce_list.callback(cog, ctx, None)

    ctx.send.assert_called_once()
    assert "no valid custom emojis" in ctx.send.call_args[0][0]


# ---------------------------------------------------------------------------
# dpytest integration
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def dpytest_bot() -> AsyncGenerator[dpy_commands.Bot, None]:
    intents = discord.Intents.default()
    intents.members = True
    intents.guilds = True

    bot = dpy_commands.Bot(command_prefix="!", intents=intents)
    await bot._async_setup_hook()  # type: ignore[attr-defined]
    dpytest.configure(bot)

    yield bot

    await dpytest.empty_queue()


@pytest.mark.asyncio
async def test_dpytest_ce_list_self_no_emojis(dpytest_bot: dpy_commands.Bot) -> None:
    """Invoking ce_list callback when user has no emojis sends the appropriate message.

    We invoke the callback directly because Redbot's ``@checks.is_owner()`` decorator
    requires a full Red bot environment incompatible with plain discord.py + dpytest.
    """
    config_mock = MagicMock(spec=Config)
    config_mock.register_guild = MagicMock()

    guild_group = MagicMock()
    guild_group.required_role_id = AsyncMock(return_value=None)
    guild_group.user_limits = AsyncMock(return_value={})
    guild_group.emoji_ownership = AsyncMock(return_value={})
    config_mock.guild = MagicMock(return_value=guild_group)

    with patch("customemoji.customemoji.Config.get_conf", return_value=config_mock):
        cog = CustomEmoji(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock
    dpytest_bot.is_mod = AsyncMock(return_value=False)  # type: ignore[attr-defined]
    await dpytest_bot.add_cog(cog)

    guild = dpytest.get_config().guilds[0]
    author = MagicMock(spec=discord.Member)
    author.id = dpytest.get_config().members[0].id
    channel_mock = MagicMock()
    channel_mock.send = AsyncMock()

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = author
    ctx.send = channel_mock.send

    await cog.ce_list.callback(cog, ctx, None)  # type: ignore[arg-type]

    channel_mock.send.assert_called_once()
    assert "no custom emojis" in channel_mock.send.call_args[0][0]
