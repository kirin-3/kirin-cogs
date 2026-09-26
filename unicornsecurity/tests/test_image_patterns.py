"""Unit tests for is_image_url pattern matching in unicornsecurity."""

from typing import cast
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


# --- tenor allowlist and probe destinations ---


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://tenor.com/view/cat-gif-123", True),
        ("https://media.tenor.com/abc/cat.gif", True),
        ("https://evil.example/cat.png?ref=tenor.com", False),
        ("https://tenor.com.evil.example/cat.png", False),
        ("https://nottenor.com/cat.png", False),
    ],
)
def test_is_tenor_url_checks_the_real_host(url: str, expected: bool) -> None:
    from unicornsecurity.imagefilter import is_tenor_url

    assert is_tenor_url(url) is expected


@pytest.mark.asyncio
async def test_non_tenor_image_with_tenor_in_the_query_is_deleted(cog: ImageFilter) -> None:
    cast(MagicMock, cog.config).guild.return_value.target_channel_id = AsyncMock(return_value=1319688029530492948)
    message = MagicMock()
    message.author.bot = False
    message.channel.id = 1319688029530492948
    message.channel.send = AsyncMock()
    message.content = "https://evil.example/cat.png?ref=tenor.com"
    message.attachments = []
    message.delete = AsyncMock()

    await cog.on_message(message)

    message.delete.assert_awaited_once()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.5/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x",
        "http://[::ffff:127.0.0.1]/x",
        "file:///etc/passwd",
    ],
)
def test_probe_refuses_non_public_destinations(url: str) -> None:
    from unicornsecurity.imagefilter import is_allowed_destination

    assert is_allowed_destination(url) is False


@pytest.mark.asyncio
async def test_resolver_refuses_names_that_resolve_to_private_addresses() -> None:
    from unicornsecurity.imagefilter import _PublicResolver

    private = [{"hostname": "x", "host": "192.168.1.1", "port": 80, "family": 2, "proto": 0, "flags": 0}]
    with (
        patch("aiohttp.ThreadedResolver.resolve", new=AsyncMock(return_value=private)),
        pytest.raises(OSError),
    ):
        await _PublicResolver().resolve("internal.example", 80)


@pytest.mark.asyncio
async def test_probe_does_not_follow_a_redirect_to_an_internal_address(cog: ImageFilter) -> None:
    redirect = MagicMock()
    redirect.status = 302
    redirect.headers = {"Location": "http://127.0.0.1/image.png"}
    redirect.__aenter__ = AsyncMock(return_value=redirect)
    redirect.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.head = MagicMock(return_value=redirect)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=session):
        assert await cog.is_image_url("https://example.com/redirect") is False

    session.head.assert_called_once_with("https://example.com/redirect", allow_redirects=False)


@pytest.mark.asyncio
async def test_edit_that_adds_an_image_is_filtered(cog: ImageFilter) -> None:
    cast(MagicMock, cog.config).guild.return_value.target_channel_id = AsyncMock(return_value=1319688029530492948)
    before = MagicMock(content="hello", attachments=[])
    after = MagicMock()
    after.author.bot = False
    after.channel.id = 1319688029530492948
    after.channel.send = AsyncMock()
    after.content = "https://example.com/cat.png"
    after.attachments = []
    after.delete = AsyncMock()

    await cog.on_raw_message_edit(MagicMock(cached_message=before, message=after))

    after.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_link_preview_edit_is_not_rechecked(cog: ImageFilter) -> None:
    message = MagicMock(content="https://example.com/cat.png", attachments=[])
    message.delete = AsyncMock()

    await cog.on_raw_message_edit(MagicMock(cached_message=message, message=message))

    message.delete.assert_not_called()
