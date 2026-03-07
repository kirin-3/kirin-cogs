"""dpytest integration tests for unicornimage: hordegen and premium gate."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from unicornimage.unicornimage import UnicornImage


def make_cog(is_owner: bool = False, premium_role_id: int | None = None) -> UnicornImage:
    config = MagicMock(spec=Config)
    config.horde_api_key = AsyncMock(return_value="test-key")
    config.modal_app_name = AsyncMock(return_value="text2image")
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


def make_ctx(guild: MagicMock | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.guild = guild or MagicMock()
    ctx.author = MagicMock()
    ctx.author.id = 42
    ctx.author.roles = []
    ctx.defer = AsyncMock()
    ctx.send = AsyncMock()
    ctx.interaction = None
    return ctx


# --- hordegen / genfree ---


@pytest.mark.asyncio
async def test_gen_free_sends_file_on_success() -> None:
    """genfree sends a discord.File when horde returns bytes."""
    cog = make_cog()
    ctx = make_ctx()

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=[fake_png])
    cog.get_horde_client = AsyncMock(return_value=mock_client)

    await cog.gen_free.callback(cog, ctx, prompt="a cat", style=None, style2=None, style3=None, negative_prompt=None)  # type: ignore[attr-defined]

    ctx.send.assert_called_once()
    call_kwargs = ctx.send.call_args[1]
    assert "file" in call_kwargs


@pytest.mark.asyncio
async def test_gen_free_handles_empty_response() -> None:
    """genfree handles empty response from Horde gracefully."""
    cog = make_cog()
    ctx = make_ctx()

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=[])
    cog.get_horde_client = AsyncMock(return_value=mock_client)

    await cog.gen_free.callback(cog, ctx, prompt="a dog", style=None, style2=None, style3=None, negative_prompt=None)  # type: ignore[attr-defined]

    ctx.send.assert_called()
    assert "Failed" in ctx.send.call_args[0][0]


# --- premium gate for gen command ---


@pytest.mark.asyncio
async def test_gen_premium_denied_without_role() -> None:
    """gen command sends denied message when user is not premium."""
    cog = make_cog(is_owner=False, premium_role_id=None)
    ctx = make_ctx()

    await cog.gen_premium.callback(  # type: ignore[attr-defined]
        cog,  # pyright: ignore[reportArgumentType]
        ctx,
        prompt="a cat",
        model="flux",
        batch_size=1,
        style=None,
        style2=None,
        style3=None,
        style4=None,
        style5=None,
        negative_prompt=None,
    )

    ctx.send.assert_called_once()
    sent_text: str = ctx.send.call_args[0][0]
    assert "Supporters" in sent_text or "PREMIUM" in sent_text.upper() or "🔒" in sent_text


@pytest.mark.asyncio
async def test_gen_premium_allowed_for_owner() -> None:
    """gen command proceeds when user is owner (premium check passes)."""
    cog = make_cog(is_owner=True)
    ctx = make_ctx()

    # Mock the full chain so it returns quickly
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=[b"\x89PNG" + b"\x00" * 50])
    cog.get_modal_client = AsyncMock(return_value=mock_client)

    with patch("unicornimage.unicornimage.MODELS", {"flux": {"id": "m1", "base": "Flux", "name": "Flux"}}):
        await cog.gen_premium.callback(  # type: ignore[attr-defined]
            cog,  # pyright: ignore[reportArgumentType]
            ctx,
            prompt="a cat",
            model="flux",
            batch_size=1,
            style=None,
            style2=None,
            style3=None,
            style4=None,
            style5=None,
            negative_prompt=None,
        )

    # ctx.defer should have been called (means premium check passed)
    ctx.defer.assert_called_once()
