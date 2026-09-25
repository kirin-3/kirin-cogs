import hashlib
import io
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import discord

from .unicornia.web import DOWNLOAD_TIMEOUT


class Embed:
    CACHE_DIR = Path(__file__).parent / "image_cache"

    @classmethod
    async def get_image(cls, session: aiohttp.ClientSession, url: str) -> Path:
        """Download ``url`` into the cache, or return it from there.

        Raises:
            aiohttp.ClientError, TimeoutError: The image couldn't be downloaded.
        """
        # named after a hash of the URL, as different URLs often end in the same file name
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        cache_path = cls.CACHE_DIR / f"{url_hash}{Path(urlparse(url).path).suffix}"

        if cache_path.exists():
            return cache_path

        async with session.get(url, timeout=DOWNLOAD_TIMEOUT, raise_for_status=True) as response:
            content = await response.read()

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
        return cache_path

    @classmethod
    async def spoiler_image(cls, session: aiohttp.ClientSession, url: str) -> discord.File:
        """The image at ``url`` as a spoilered attachment, downloaded through the cache.

        Raises:
            aiohttp.ClientError, TimeoutError: The image couldn't be downloaded.
        """
        image_path = await cls.get_image(session, url)
        return discord.File(
            io.BytesIO(image_path.read_bytes()),
            filename=f"SPOILER_image{image_path.suffix}",
            spoiler=True,
        )
