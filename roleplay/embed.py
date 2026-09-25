import hashlib
import io
from pathlib import Path
from urllib.parse import urlparse

import discord
import requests


class Embed:
    CACHE_DIR = Path(__file__).parent / "image_cache"

    # @classmethod
    # def create(
    #     cls,
    #     title=None,
    #     description=None,
    #     color=const.EMBED_COLOR,
    #     image=None,
    #     thumnail=None,
    #     authors=None,
    #     credits=None,
    #     spoiler=False,
    # ):
    #     embed = discord.Embed()

    #     if authors:
    #         if isinstance(authors, list):
    #             authors = ", ".join(authors)
    #         embed.set_author(authors)

    #     footer = const.EMBED_FOOTER
    #     if action.credits:
    #         footer = f'{footer}\ncredits: {", ".join(action.credits)}'
    #     self.logger.debug(f"footer : {footer}")

    #     return embed

    @classmethod
    def get_image(cls, url: str) -> Path:
        """Download ``url`` into the cache, or return it from there.

        Raises:
            requests.RequestException: The image couldn't be downloaded.
        """
        # named after a hash of the URL, as different URLs often end in the same file name
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        cache_path = cls.CACHE_DIR / f"{url_hash}{Path(urlparse(url).path).suffix}"

        if cache_path.exists():
            return cache_path

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(response.content)
        return cache_path

    @classmethod
    def spoiler_image(cls, url: str, embed: discord.Embed) -> tuple[discord.Embed, discord.File]:
        image_path = cls.get_image(url)
        file_extension = image_path.suffix

        with image_path.open("rb") as file:
            file_content = file.read()

        file = discord.File(
            io.BytesIO(file_content),
            filename=f"SPOILER_image{file_extension}",
            spoiler=True,
        )
        # embed.set_image(url=f"attachment://SPOILER_image{file_extension}")
        return embed, file


if __name__ == "__main__":
    # Example usage
    image_url = "https://cdn.weeb.sh/images/rJaog0FtZ.gif"
    cached_image_path = Embed.get_image(image_url)
    print(f"Cached image path: {cached_image_path}")
