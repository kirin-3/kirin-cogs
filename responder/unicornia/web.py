import re

import aiohttp

IMG_SRC_PATTERN = re.compile(r"<img[^>]+src=\"([^\"]+)\"")


async def get_tenor_gifs(search_term: str, limit: int = 10) -> list[str]:
    """Scrape GIF URLs from Tenor's search page."""
    url = f"https://tenor.com/search/{search_term}-gifs"
    async with (
        aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session,
        session.get(url) as response,
    ):
        response.raise_for_status()
        html = await response.text()

    return [src for src in IMG_SRC_PATTERN.findall(html) if "gif" in src][:limit]
