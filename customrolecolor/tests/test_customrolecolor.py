"""Unit, async, and dpytest integration tests for the CustomRoleColor cog."""

import inspect
import io
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import discord.ext.commands as dpy_commands
import discord.ext.test as dpytest
import pytest
import pytest_asyncio
from redbot.core import Config

from customrolecolor.customrolecolor import PALETTE_COLORS, CustomRoleColor, generate_palette_image

# ---------------------------------------------------------------------------
# Pure-function tests
# ---------------------------------------------------------------------------


def test_generate_palette_image_returns_bytes_io() -> None:
    result = generate_palette_image()
    assert isinstance(result, io.BytesIO)
    data = result.read()
    assert len(data) > 0
    # PNG magic bytes
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_palette_colors_all_have_valid_hex() -> None:
    for name, hex_code in PALETTE_COLORS:
        assert hex_code.startswith("#"), f"{name} missing # prefix"
        assert len(hex_code) == 7, f"{name} hex not 7 chars"
        int(hex_code[1:], 16)  # raises ValueError if invalid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock()  # no spec so loop and other attrs work freely
    bot.owner_ids = {111}
    return bot


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    guild_group = MagicMock()
    guild_group.assignments = AsyncMock(return_value={})
    guild_group.assignments.set_raw = AsyncMock()
    config.guild = MagicMock(return_value=guild_group)
    config.register_guild = MagicMock()
    return config


@pytest_asyncio.fixture
async def cog(bot_mock: MagicMock, config_mock: MagicMock) -> CustomRoleColor:
    with patch("customrolecolor.customrolecolor.Config.get_conf", return_value=config_mock):
        c = CustomRoleColor(bot_mock)
    c.config = config_mock
    return c


def _make_ctx(
    bot: MagicMock,
    *,
    guild_id: int = 1,
    author_id: int = 500,
    has_manage_roles: bool = False,
    attachments: list | None = None,
    guild_features: list | None = None,
) -> MagicMock:
    me = MagicMock(spec=discord.Member)
    top_role = MagicMock(spec=discord.Role)
    top_role.position = 100
    me.top_role = top_role

    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    guild.me = me
    guild.features = guild_features or []

    author = MagicMock(spec=discord.Member)
    author.id = author_id
    author.display_name = "TestUser"
    author.configure_mock(**{"__str__.return_value": "TestUser#0000"})
    perms = MagicMock(spec=discord.Permissions)
    perms.manage_roles = has_manage_roles
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


async def _role_edit_with_icon(
    name: str = discord.utils.MISSING,
    colour: discord.Color = discord.utils.MISSING,
    secondary_colour: discord.Color | None = discord.utils.MISSING,
    tertiary_colour: discord.Color | None = discord.utils.MISSING,
    mentionable: bool = discord.utils.MISSING,
    display_icon: str | bytes | None = discord.utils.MISSING,
    reason: str | None = None,
) -> None:
    """Async stub whose signature includes ``display_icon`` for inspect.signature checks."""


# Pre-compute the signature once
_EDIT_WITH_ICON_SIG = inspect.signature(_role_edit_with_icon)


def _make_role(*, position: int = 10, name: str = "MyRole") -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.position = position
    role.name = name
    role.mention = f"@{name}"
    # Set __signature__ on the AsyncMock so that inspect.signature(role.edit)
    # includes 'display_icon', which the cog checks before setting role icons.
    edit_mock = AsyncMock()
    edit_mock.__signature__ = _EDIT_WITH_ICON_SIG
    role.edit = edit_mock
    role.__ge__ = lambda self, other: self.position >= other.position
    role.__gt__ = lambda self, other: self.position > other.position
    return role


# ---------------------------------------------------------------------------
# assignrole
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assignrole_role_too_high(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, has_manage_roles=True)

    role = _make_role(position=200)
    ctx.guild.me.top_role.position = 100

    await cog.assignrole.callback(cog, ctx, ctx.author, role)  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("I can't manage that role (it's higher than or equal to my top role).")


@pytest.mark.asyncio
async def test_assignrole_success(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, has_manage_roles=True)

    member = MagicMock(spec=discord.Member)
    member.id = 42
    member.mention = "@target"

    role = _make_role(position=50)
    role.mention = "@MyRole"
    ctx.guild.me.top_role.position = 100

    guild_group = config_mock.guild.return_value
    guild_group.assignments.set_raw = AsyncMock()

    await cog.assignrole.callback(cog, ctx, member, role)  # pyright: ignore[reportArgumentType]

    guild_group.assignments.set_raw.assert_called_once_with("42", value=role.id)
    ctx.send.assert_called_once()
    assert "can now manage" in ctx.send.call_args[0][0]


# ---------------------------------------------------------------------------
# myrolecolor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_myrolecolor_no_assignment(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={})

    await cog.myrolecolor.callback(cog, ctx, "#ff0000")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("You don't have a role assigned for color management.")


@pytest.mark.asyncio
async def test_myrolecolor_role_not_found(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})
    ctx.guild.get_role = MagicMock(return_value=None)

    await cog.myrolecolor.callback(cog, ctx, "#ff0000")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("The assigned role no longer exists.")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command_name", "args", "kwargs"),
    [
        ("myrolecolor", ("#ff0000",), {}),
        ("myrolename", (), {"new_name": "New Name"}),
        ("myroleicon", ("🎉",), {}),
        ("myrolementionable", ("on",), {}),
    ],
)
async def test_management_rejects_member_who_lost_assigned_role(
    cog: CustomRoleColor,
    bot_mock: MagicMock,
    config_mock: MagicMock,
    command_name: str,
    args: tuple,
    kwargs: dict,
) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, guild_features=["ROLE_ICONS"])
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})
    role = _make_role(position=50)
    role.id = 999
    ctx.guild.get_role = MagicMock(return_value=role)
    ctx.author.get_role = MagicMock(return_value=None)

    command = getattr(cog, command_name)
    await command.callback(cog, ctx, *args, **kwargs)

    ctx.send.assert_called_once_with("You no longer have the role assigned for management.")
    role.edit.assert_not_awaited()


@pytest.mark.asyncio
async def test_myrolecolor_role_too_high(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=200)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolecolor.callback(cog, ctx, "#ff0000")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("I can't manage that role (it's higher than or equal to my top role).")


@pytest.mark.asyncio
async def test_myrolecolor_invalid_hex(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolecolor.callback(cog, ctx, "notahex")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once()
    assert "valid hex color" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_myrolecolor_flat_color_success(
    cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock
) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolecolor.callback(cog, ctx, "#ff0000")  # pyright: ignore[reportArgumentType]

    role.edit.assert_called_once()
    call_kwargs = role.edit.call_args[1]
    assert call_kwargs["colour"] == discord.Color(0xFF0000)
    assert call_kwargs["secondary_colour"] is None
    ctx.send.assert_called_once()
    assert "#ff0000" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_myrolecolor_gradient_success(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolecolor.callback(cog, ctx, "#ff0000", "#00ff00")  # pyright: ignore[reportArgumentType]

    role.edit.assert_called_once()
    ctx.send.assert_called_once()
    assert "gradient" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_myrolecolor_holographic(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolecolor.callback(cog, ctx, "holographic")  # pyright: ignore[reportArgumentType]

    role.edit.assert_called_once()
    ctx.send.assert_called_once()
    assert "holographic" in ctx.send.call_args[0][0]


@pytest.mark.asyncio
async def test_myrolecolor_forbidden(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    # Override edit with a side-effect while keeping display_icon in the signature
    forbidden_edit = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perm"))
    forbidden_edit.__signature__ = _EDIT_WITH_ICON_SIG
    role.edit = forbidden_edit
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolecolor.callback(cog, ctx, "#ff0000")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("I don't have permission to edit that role.")


# ---------------------------------------------------------------------------
# myrolename
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_myrolename_no_assignment(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={})

    await cog.myrolename.callback(cog, ctx, new_name="Cool Name")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("You don't have a role assigned for name management.")


@pytest.mark.asyncio
async def test_myrolename_empty_name(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolename.callback(cog, ctx, new_name="")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("Role name must be between 1 and 100 characters.")


@pytest.mark.asyncio
async def test_myrolename_too_long(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolename.callback(cog, ctx, new_name="x" * 101)  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("Role name must be between 1 and 100 characters.")


@pytest.mark.asyncio
async def test_myrolename_success(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolename.callback(cog, ctx, new_name="Awesome Role")  # pyright: ignore[reportArgumentType]

    role.edit.assert_called_once()
    ctx.send.assert_called_once()
    assert "Awesome Role" in ctx.send.call_args[0][0]


# ---------------------------------------------------------------------------
# myroleicon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_myroleicon_no_assignment(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={})

    await cog.myroleicon.callback(cog, ctx, emoji="🎉")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("You don't have a role assigned for icon management.")


@pytest.mark.asyncio
async def test_myroleicon_no_role_icons_feature(
    cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock
) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, guild_features=[])
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myroleicon.callback(cog, ctx, emoji="🎉")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("This server does not have the ROLE_ICONS feature (requires Level 2 boost).")


@pytest.mark.asyncio
async def test_myroleicon_custom_emoji_rejected(
    cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock
) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, guild_features=["ROLE_ICONS"])
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myroleicon.callback(cog, ctx, emoji="<:customemoji:123456>")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("Only unicode emoji are supported as role icons, not custom Discord emoji.")


@pytest.mark.asyncio
async def test_myroleicon_no_emoji_no_attachment(
    cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock
) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, guild_features=["ROLE_ICONS"])
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myroleicon.callback(cog, ctx, emoji=None)  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("Please attach a PNG or JPEG image, or provide a unicode emoji as an argument.")


@pytest.mark.asyncio
async def test_myroleicon_attachment_wrong_type(
    cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock
) -> None:
    attachment = MagicMock(spec=discord.Attachment)
    attachment.filename = "icon.gif"
    attachment.size = 1024
    ctx = _make_ctx(bot_mock, author_id=500, guild_features=["ROLE_ICONS"], attachments=[attachment])
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myroleicon.callback(cog, ctx, emoji=None)  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("The icon must be a PNG or JPEG image.")


@pytest.mark.asyncio
async def test_myroleicon_attachment_too_large(
    cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock
) -> None:
    attachment = MagicMock(spec=discord.Attachment)
    attachment.filename = "icon.png"
    attachment.size = 300 * 1024
    ctx = _make_ctx(bot_mock, author_id=500, guild_features=["ROLE_ICONS"], attachments=[attachment])
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myroleicon.callback(cog, ctx, emoji=None)  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("The image must be under 256 KB.")


@pytest.mark.asyncio
async def test_myroleicon_unicode_emoji_success(
    cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock
) -> None:
    ctx = _make_ctx(bot_mock, author_id=500, guild_features=["ROLE_ICONS"])
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myroleicon.callback(cog, ctx, emoji="🎉")  # pyright: ignore[reportArgumentType]

    role.edit.assert_called_once()
    ctx.send.assert_called_once()
    assert "🎉" in ctx.send.call_args[0][0]


# ---------------------------------------------------------------------------
# myrolementionable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mentionable_no_assignment(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={})

    await cog.myrolementionable.callback(cog, ctx, "on")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("You don't have a role assigned for mention management.")


@pytest.mark.asyncio
async def test_mentionable_invalid_state(cog: CustomRoleColor, bot_mock: MagicMock, config_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolementionable.callback(cog, ctx, "maybe")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("Please specify `on` or `off`.")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,expected",
    [
        ("on", True),
        ("true", True),
        ("yes", True),
        ("off", False),
        ("false", False),
        ("no", False),
    ],
)
async def test_mentionable_valid_states(
    state: str,
    expected: bool,
    cog: CustomRoleColor,
    bot_mock: MagicMock,
    config_mock: MagicMock,
) -> None:
    ctx = _make_ctx(bot_mock, author_id=500)
    config_mock.guild.return_value.assignments = AsyncMock(return_value={"500": 999})

    role = _make_role(position=50)
    ctx.guild.me.top_role.position = 100
    ctx.guild.get_role = MagicMock(return_value=role)

    await cog.myrolementionable.callback(cog, ctx, state)  # pyright: ignore[reportArgumentType]

    role.edit.assert_called_once()
    call_kwargs = role.edit.call_args[1]
    assert call_kwargs["mentionable"] is expected


# ---------------------------------------------------------------------------
# colorpreview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_colorpreview_invalid_hex(cog: CustomRoleColor, bot_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    await cog.colorpreview.callback(cog, ctx, "zzzzzz")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("Invalid hex color.")


@pytest.mark.asyncio
async def test_colorpreview_short_hex(cog: CustomRoleColor, bot_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)
    await cog.colorpreview.callback(cog, ctx, "#fff")  # pyright: ignore[reportArgumentType]
    ctx.send.assert_called_once_with("Please provide a valid hex color (e.g., #ff0000).")


@pytest.mark.asyncio
async def test_colorpreview_success(cog: CustomRoleColor, bot_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)

    async def run_executor(executor, func):
        return func()

    bot_mock.loop.run_in_executor = AsyncMock(side_effect=run_executor)

    await cog.colorpreview.callback(cog, ctx, "#ff0000")  # pyright: ignore[reportArgumentType]

    ctx.send.assert_called_once()
    _, kwargs = ctx.send.call_args
    assert "embed" in kwargs
    assert "file" in kwargs


# ---------------------------------------------------------------------------
# colorpalette
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_colorpalette_success(cog: CustomRoleColor, bot_mock: MagicMock) -> None:
    ctx = _make_ctx(bot_mock)

    async def run_executor(executor, func):
        return func()

    bot_mock.loop.run_in_executor = AsyncMock(side_effect=run_executor)

    await cog.colorpalette.callback(cog, ctx)  # pyright: ignore[reportArgumentType]

    ctx.send.assert_called_once()
    _, kwargs = ctx.send.call_args
    assert "embed" in kwargs
    assert "file" in kwargs


# ---------------------------------------------------------------------------
# dpytest integration
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
async def test_dpytest_myrolecolor_no_assignment(dpytest_bot: dpy_commands.Bot) -> None:
    """Dispatching myrolecolor callback when user has no role sends the no-assignment message.

    We invoke the callback directly because Redbot's permission system requires a full
    Red bot environment which is incompatible with plain discord.py + dpytest.
    """
    config_mock = MagicMock(spec=Config)
    config_mock.register_guild = MagicMock()

    guild_group = MagicMock()
    guild_group.assignments = AsyncMock(return_value={})
    config_mock.guild = MagicMock(return_value=guild_group)

    with patch("customrolecolor.customrolecolor.Config.get_conf", return_value=config_mock):
        cog = CustomRoleColor(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock
    await dpytest_bot.add_cog(cog)

    guild = dpytest.get_config().guilds[0]
    channel = dpytest.get_config().channels[0]
    author = MagicMock()
    author.id = 500
    channel_mock = MagicMock()
    channel_mock.send = AsyncMock()
    channel_mock.id = channel.id

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = author
    ctx.message = MagicMock(spec=discord.Message)
    ctx.message.attachments = []
    ctx.send = channel_mock.send

    await cog.myrolecolor.callback(cog, ctx, "#ff0000")  # type: ignore[arg-type]

    channel_mock.send.assert_called_once()
    assert "don't have a role assigned" in channel_mock.send.call_args[0][0]


@pytest.mark.asyncio
async def test_dpytest_myrolename_no_assignment(dpytest_bot: dpy_commands.Bot) -> None:
    """Dispatching myrolename callback when user has no role sends the no-assignment message."""
    config_mock = MagicMock(spec=Config)
    config_mock.register_guild = MagicMock()

    guild_group = MagicMock()
    guild_group.assignments = AsyncMock(return_value={})
    config_mock.guild = MagicMock(return_value=guild_group)

    with patch("customrolecolor.customrolecolor.Config.get_conf", return_value=config_mock):
        cog = CustomRoleColor(dpytest_bot)  # type: ignore[arg-type]
    cog.config = config_mock
    await dpytest_bot.add_cog(cog)

    guild = dpytest.get_config().guilds[0]
    channel = dpytest.get_config().channels[0]
    author = MagicMock()
    author.id = 500
    channel_mock = MagicMock()
    channel_mock.send = AsyncMock()
    channel_mock.id = channel.id

    ctx = MagicMock()
    ctx.guild = guild
    ctx.author = author
    ctx.send = channel_mock.send

    await cog.myrolename.callback(cog, ctx, new_name="new name")  # type: ignore[arg-type]

    channel_mock.send.assert_called_once()
    assert "don't have a role assigned" in channel_mock.send.call_args[0][0]
