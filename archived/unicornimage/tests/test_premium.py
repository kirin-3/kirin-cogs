"""Unit tests for is_premium in unicornimage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from unicornimage.unicornimage import UnicornImage


def make_cog(is_owner: bool = False, premium_role_id: int | None = None) -> UnicornImage:
    config = MagicMock(spec=Config)
    config.horde_api_key = AsyncMock(return_value="key")
    config.modal_app_name = AsyncMock(return_value="app")
    config.modal_prompt = AsyncMock(return_value="")

    def _guild(*args: object, **kwargs: object) -> object:
        _role_id = premium_role_id

        class _Group:
            def __getattr__(self, name: str) -> AsyncMock:
                if name == "premium_role_id":
                    am = AsyncMock(return_value=_role_id)
                    am.set = AsyncMock()
                    return am
                am = AsyncMock(return_value=None)
                am.set = AsyncMock()
                return am

        return _Group()

    config.guild.side_effect = _guild

    bot = MagicMock(spec=Red)
    bot.is_owner = AsyncMock(return_value=is_owner)
    bot.owner_ids = set()
    bot.session = MagicMock()

    with patch("unicornimage.unicornimage.Config.get_conf", return_value=config):
        cog = UnicornImage(bot)  # type: ignore[arg-type]
    cog.config = config
    return cog


@pytest.mark.asyncio
async def test_is_premium_owner_always_true() -> None:
    """Bot owner is always premium."""
    cog = make_cog(is_owner=True)

    ctx = MagicMock()
    ctx.author = MagicMock()
    ctx.guild = MagicMock()

    result = await cog.is_premium(ctx)
    assert result is True


@pytest.mark.asyncio
async def test_is_premium_no_guild_returns_false() -> None:
    """Without a guild context (DMs) is_premium returns False."""
    cog = make_cog(is_owner=False)

    ctx = MagicMock()
    ctx.author = MagicMock()
    ctx.guild = None

    result = await cog.is_premium(ctx)
    assert result is False


@pytest.mark.asyncio
async def test_is_premium_no_role_configured_returns_false() -> None:
    """No premium role configured means no access."""
    cog = make_cog(is_owner=False, premium_role_id=None)

    ctx = MagicMock()
    ctx.author = MagicMock()
    ctx.guild = MagicMock()

    result = await cog.is_premium(ctx)
    assert result is False


@pytest.mark.asyncio
async def test_is_premium_member_with_role_returns_true() -> None:
    """Member who has the premium role is premium."""
    role_id = 123456789
    cog = make_cog(is_owner=False, premium_role_id=role_id)

    role = MagicMock()
    role.id = role_id

    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.guild.get_role = MagicMock(return_value=role)
    ctx.author = MagicMock(spec=["id", "roles"])
    ctx.author.roles = [role]

    import discord

    # Make isinstance(ctx.author, discord.Member) return True
    ctx.author.__class__ = discord.Member

    result = await cog.is_premium(ctx)
    assert result is True


@pytest.mark.asyncio
async def test_is_premium_member_without_role_returns_false() -> None:
    """Member who doesn't have the premium role is not premium."""
    role_id = 123456789
    cog = make_cog(is_owner=False, premium_role_id=role_id)

    premium_role = MagicMock()
    premium_role.id = role_id

    other_role = MagicMock()
    other_role.id = 999

    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.guild.get_role = MagicMock(return_value=premium_role)
    ctx.author = MagicMock(spec=["id", "roles"])
    ctx.author.roles = [other_role]

    import discord

    ctx.author.__class__ = discord.Member

    result = await cog.is_premium(ctx)
    assert result is False
