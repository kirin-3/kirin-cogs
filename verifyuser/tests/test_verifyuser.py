"""Tests for the hybrid Member-based VerifyUser command."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from redbot.core.bot import Red
from redbot.core.commands import Context

from verifyuser.verifyuser import VerifyUser


def _role(role_id: int, *, above_bot: bool = False) -> MagicMock:
    role = MagicMock(spec=discord.Role)
    role.id = role_id
    role.managed = False
    role.is_default.return_value = False
    role.__ge__.return_value = above_bot
    return role


@pytest.fixture
def cog() -> VerifyUser:
    return VerifyUser(MagicMock(spec=Red))


@pytest.fixture
def setup_objects() -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    ctx = MagicMock(spec=Context)
    guild = MagicMock(spec=discord.Guild)
    actor = MagicMock(spec=discord.Member)
    target = MagicMock(spec=discord.Member)
    bot_member = MagicMock(spec=discord.Member)
    bot_top = _role(900)
    actor_top = _role(800)
    target_top = _role(100)
    actor_top.__ge__.return_value = True
    target_top.__ge__.return_value = False
    guild.me = bot_member
    guild.me.id = 999
    guild.me.guild_permissions.manage_roles = True
    guild.me.top_role = bot_top
    guild.owner_id = 1
    guild.id = 55
    actor.id = 10
    actor.top_role = actor_top
    target.id = 20
    target.bot = False
    target.top_role = target_top
    target.roles = []
    target.mention = "@target"
    target.add_roles = AsyncMock()
    ctx.guild = guild
    ctx.author = actor
    ctx.send = AsyncMock()
    return ctx, guild, actor, target


@pytest.mark.asyncio
async def test_requires_authorized_role(cog: VerifyUser, setup_objects) -> None:
    ctx, guild, actor, target = setup_objects
    guild.get_role.return_value = None
    actor.roles = []

    await cog.verifyuser.callback(cog, ctx, target)  # pyright: ignore[reportArgumentType]

    ctx.send.assert_awaited_once_with("You don't have permission to use this command.", ephemeral=True)


@pytest.mark.asyncio
async def test_rejects_unmanageable_verification_role(cog: VerifyUser, setup_objects) -> None:
    ctx, guild, actor, target = setup_objects
    authorized = _role(cog.AUTHORIZED_ROLE_ID)
    verification = _role(cog.VERIFICATION_ROLE_ID, above_bot=True)
    actor.roles = [authorized]
    guild.get_role.side_effect = lambda role_id: authorized if role_id == authorized.id else verification

    await cog.verifyuser.callback(cog, ctx, target)  # pyright: ignore[reportArgumentType]

    ctx.send.assert_awaited_once_with(
        "I can't assign that role (it's higher than or equal to my top role).", ephemeral=True
    )
    target.add_roles.assert_not_awaited()


@pytest.mark.asyncio
async def test_verifyuser_success(cog: VerifyUser, setup_objects) -> None:
    ctx, guild, actor, target = setup_objects
    authorized = _role(cog.AUTHORIZED_ROLE_ID)
    verification = _role(cog.VERIFICATION_ROLE_ID)
    actor.roles = [authorized]
    guild.get_role.side_effect = lambda role_id: authorized if role_id == authorized.id else verification
    actor.__str__.return_value = "Moderator"

    await cog.verifyuser.callback(cog, ctx, target)  # pyright: ignore[reportArgumentType]

    target.add_roles.assert_awaited_once_with(verification, reason="Verified by Moderator")
    ctx.send.assert_awaited_once_with("Successfully verified @target!")


@pytest.mark.asyncio
async def test_verifyuser_http_error_is_safe(cog: VerifyUser, setup_objects) -> None:
    ctx, guild, actor, target = setup_objects
    authorized = _role(cog.AUTHORIZED_ROLE_ID)
    verification = _role(cog.VERIFICATION_ROLE_ID)
    actor.roles = [authorized]
    guild.get_role.side_effect = lambda role_id: authorized if role_id == authorized.id else verification
    target.add_roles.side_effect = discord.HTTPException(MagicMock(), "private raw Discord failure")

    await cog.verifyuser.callback(cog, ctx, target)  # pyright: ignore[reportArgumentType]

    message = ctx.send.await_args.args[0]
    assert "private raw Discord failure" not in message
    assert ctx.send.await_args.kwargs["ephemeral"] is True


@pytest.mark.asyncio
async def test_verifyuser_self_target_rejected(cog: VerifyUser, setup_objects) -> None:
    ctx, guild, actor, target = setup_objects
    authorized = _role(cog.AUTHORIZED_ROLE_ID)
    verification = _role(cog.VERIFICATION_ROLE_ID)
    actor.roles = [authorized]
    target.id = actor.id
    guild.get_role.side_effect = lambda role_id: authorized if role_id == authorized.id else verification

    await cog.verifyuser.callback(cog, ctx, target)  # pyright: ignore[reportArgumentType]

    ctx.send.assert_awaited_once_with("You cannot use this command on yourself.", ephemeral=True)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda guild, actor, target, role: setattr(guild.me.guild_permissions, "manage_roles", False),
            "I do not have the Manage Roles permission.",
        ),
        (
            lambda guild, actor, target, role: setattr(role, "managed", True),
            "This role cannot be assigned because it is a managed or default role.",
        ),
        (
            lambda guild, actor, target, role: role.is_default.configure_mock(return_value=True),
            "This role cannot be assigned because it is a managed or default role.",
        ),
        (
            lambda guild, actor, target, role: setattr(target, "id", guild.me.id),
            "I cannot verify myself.",
        ),
        (
            lambda guild, actor, target, role: setattr(target, "bot", True),
            "Bot accounts cannot be verified.",
        ),
        (
            lambda guild, actor, target, role: setattr(target, "id", guild.owner_id),
            "The server owner cannot be managed with this command.",
        ),
        (
            lambda guild, actor, target, role: target.top_role.__ge__.configure_mock(return_value=True),
            "I cannot manage that member because their top role is too high.",
        ),
    ],
)
def test_preflight_permission_matrix(cog: VerifyUser, setup_objects, mutate, expected: str) -> None:
    _ctx, guild, actor, target = setup_objects
    role = _role(cog.VERIFICATION_ROLE_ID)
    mutate(guild, actor, target, role)
    assert cog._preflight_role_edit(guild, actor, target, role) == expected


def test_preflight_enforces_caller_hierarchy(cog: VerifyUser, setup_objects) -> None:
    _ctx, guild, actor, target = setup_objects
    role = _role(cog.VERIFICATION_ROLE_ID)
    target.top_role.__ge__.side_effect = lambda other: other is actor.top_role
    assert cog._preflight_role_edit(guild, actor, target, role) == (
        "You cannot manage a member with an equal or higher top role."
    )


@pytest.mark.asyncio
async def test_verifyuser_forbidden_is_safe(cog: VerifyUser, setup_objects) -> None:
    ctx, guild, actor, target = setup_objects
    authorized = _role(cog.AUTHORIZED_ROLE_ID)
    verification = _role(cog.VERIFICATION_ROLE_ID)
    actor.roles = [authorized]
    guild.get_role.side_effect = lambda role_id: authorized if role_id == authorized.id else verification
    target.add_roles.side_effect = discord.Forbidden(MagicMock(), "private forbidden detail")

    await cog.verifyuser.callback(cog, ctx, target)  # pyright: ignore[reportArgumentType]

    ctx.send.assert_awaited_once_with("I don't have permission to assign roles.", ephemeral=True)
