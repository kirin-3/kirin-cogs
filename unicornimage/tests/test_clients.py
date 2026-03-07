"""Unit tests for get_horde_client and get_modal_client lazy init + caching."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from unicornimage.unicornimage import UnicornImage
from unicornimage.utils.horde import HordeClient


def make_cog() -> UnicornImage:
    config = MagicMock(spec=Config)
    config.horde_api_key = AsyncMock(return_value="test-key")
    config.modal_app_name = AsyncMock(return_value="text2image")
    config.modal_prompt = AsyncMock(return_value="")

    def _guild(*args: object, **kwargs: object) -> object:
        class _Group:
            premium_role_id = AsyncMock(return_value=None)

        return _Group()

    config.guild.side_effect = _guild

    bot = MagicMock(spec=Red)
    bot.session = MagicMock()
    bot.owner_ids = set()

    with patch("unicornimage.unicornimage.Config.get_conf", return_value=config):
        cog = UnicornImage(bot)  # type: ignore[arg-type]
    cog.config = config
    return cog


# --- get_horde_client ---


@pytest.mark.asyncio
async def test_get_horde_client_lazy_init() -> None:
    """get_horde_client returns a HordeClient on first call."""
    cog = make_cog()
    assert cog._horde_client is None

    client = await cog.get_horde_client()

    assert isinstance(client, HordeClient)
    assert cog._horde_client is not None


@pytest.mark.asyncio
async def test_get_horde_client_caching() -> None:
    """Calling get_horde_client twice returns the same instance."""
    cog = make_cog()

    client1 = await cog.get_horde_client()
    client2 = await cog.get_horde_client()

    assert client1 is client2


# --- get_modal_client ---


@pytest.mark.asyncio
async def test_get_modal_client_lazy_init() -> None:
    """get_modal_client uses asyncio.to_thread to create ModalClient."""
    cog = make_cog()
    assert cog._modal_client is None

    mock_modal = MagicMock()

    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = mock_modal
        client = await cog.get_modal_client()

    mock_to_thread.assert_called_once()
    assert client is mock_modal
    assert cog._modal_client is mock_modal


@pytest.mark.asyncio
async def test_get_modal_client_caching() -> None:
    """Calling get_modal_client twice returns the same instance without re-creating."""
    cog = make_cog()
    mock_modal = MagicMock()

    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        mock_to_thread.return_value = mock_modal
        client1 = await cog.get_modal_client()
        client2 = await cog.get_modal_client()

    # to_thread should only be called once
    assert mock_to_thread.call_count == 1
    assert client1 is client2
