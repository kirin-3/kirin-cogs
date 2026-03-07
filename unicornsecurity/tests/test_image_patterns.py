"""Unit tests for is_image_url pattern matching in unicornsecurity."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unicornsecurity.imagefilter import ImageFilter


@pytest.fixture
def cog() -> ImageFilter:
    bot = MagicMock()
    with patch("unicornsecurity.imagefilter.Config.get_conf"):
        return ImageFilter(bot)


@pytest.mark.parametrize(
    "url,expected",
    [
        # Direct image extensions
        ("https://example.com/photo.png", True),
        ("https://example.com/photo.jpg", True),
        ("https://example.com/photo.jpeg", True),
        ("https://example.com/photo.gif", True),
        ("https://example.com/photo.webp", True),
        # Imgur
        ("https://i.imgur.com/abcdef.png", True),
        ("https://imgur.com/abcdef", True),
        # Reddit
        ("https://i.redd.it/abcdef.jpg", True),
        # Discord attachments
        ("https://cdn.discordapp.com/attachments/123/456/file.png", True),
        ("https://media.discordapp.net/attachments/123/456/file.png", True),
    ],
)
@pytest.mark.asyncio
async def test_is_image_url_pattern_matches(cog: ImageFilter, url: str, expected: bool) -> None:
    """Known image URL patterns should return True without HTTP call."""
    result = await cog.is_image_url(url)
    assert result is expected


@pytest.mark.asyncio
async def test_is_image_url_non_image_url_returns_false() -> None:
    """Non-image URLs that don't match patterns should return False (HTTP returns non-image)."""
    bot = MagicMock()
    with patch("unicornsecurity.imagefilter.Config.get_conf"):
        cog = ImageFilter(bot)

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_response = AsyncMock()
        mock_response.headers.get = MagicMock(return_value="text/html")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.head = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_cls.return_value = mock_session

        result = await cog.is_image_url("https://example.com/page")
    assert result is False


@pytest.mark.asyncio
async def test_is_image_url_content_type_fallback() -> None:
    """Non-pattern URL with image content-type header returns True."""
    bot = MagicMock()
    with patch("unicornsecurity.imagefilter.Config.get_conf"):
        cog = ImageFilter(bot)

    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_response = AsyncMock()
        mock_response.headers.get = MagicMock(return_value="image/jpeg")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.head = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_cls.return_value = mock_session

        result = await cog.is_image_url("https://example.com/noextension")
    assert result is True
