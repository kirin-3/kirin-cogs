import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def fetch_image(session: aiohttp.ClientSession, url: str) -> bytes:
    """Download the image at ``url``.

    Raises:
        aiohttp.ClientError, TimeoutError: The image couldn't be downloaded, or the
            server answered with something that isn't an image (dead image hosts
            often answer 200 with an HTML page).
    """
    async with session.get(url, timeout=DOWNLOAD_TIMEOUT, raise_for_status=True) as response:
        if not response.content_type.startswith("image/"):
            raise aiohttp.ContentTypeError(
                response.request_info, response.history, message=f"not an image: {response.content_type}"
            )
        return await response.read()


async def save_image_from_url(
    session: aiohttp.ClientSession, url: str, path: Path, action_name: str, spoiler: bool = False
) -> bool | None:
    """Save the image at ``url`` into ``path / action_name``.

    The file is named after a hash of the URL (different URLs often end in the same
    file name), so running this again skips images already saved.

    Returns:
        True if the image was downloaded, False if it was already saved, or None if the
        download failed.
    """
    # Ensure the folder exists
    folder_path = path / action_name
    folder_path.mkdir(parents=True, exist_ok=True)

    # Add "SPOILER_" prefix if the spoiler flag is set
    filename_prefix = "SPOILER_" if spoiler else ""
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    suffix = Path(urlparse(url).path).suffix
    file_path = folder_path / f"{filename_prefix}{action_name}_{url_hash}{suffix}"
    if file_path.exists():
        return False

    # Download the image
    try:
        content = await fetch_image(session, url)
    except (aiohttp.ClientError, TimeoutError):
        logger.exception(f"{action_name} : Error downloading {url}.")
        return None

    # Write the image to the specified file path
    file_path.write_bytes(content)
    logger.info(f"Image saved to {file_path}")
    return True
