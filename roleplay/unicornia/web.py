import hashlib
import logging
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


def save_image_from_url(url: str, path: Path, action_name: str, spoiler: bool = False) -> bool | None:
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
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raise an error for bad status codes
    except requests.RequestException:
        logger.exception(f"{action_name} : Error downloading {url}.")
        return None

    # Write the image to the specified file path
    file_path.write_bytes(response.content)
    logger.info(f"Image saved to {file_path}")
    return True
