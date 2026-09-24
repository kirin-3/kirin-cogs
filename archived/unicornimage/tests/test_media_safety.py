"""Remote-media and concurrency configuration safety tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from unicornimage.views import LoraListView


class _Content:
    async def iter_chunked(self, size: int):
        yield b"x" * (6 * 1024 * 1024)
        yield b"y" * (6 * 1024 * 1024)


class _Response:
    status = 200
    headers = {"Content-Type": "image/png"}
    content = _Content()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.mark.asyncio
async def test_remote_preview_over_limit_is_rejected() -> None:
    session = MagicMock()
    session.get.return_value = _Response()
    view = LoraListView({"sample": {"image_url": "https://example.invalid/image.png"}}, session)

    files, names = await view.fetch_images([("sample", {"image_url": "https://example.invalid/image.png"})])

    assert files == []
    assert names == {}


@pytest.mark.asyncio
async def test_concurrency_change_rejected_while_generation_active(cog) -> None:
    ctx = MagicMock()
    ctx.send = AsyncMock()
    cog._active_generations = 1

    await cog.set_concurrency.callback(cog, ctx, 2)  # pyright: ignore[reportArgumentType]

    ctx.send.assert_awaited_once_with("Wait for active generations to finish before changing this limit.")
    cog.config.generation_limit.set.assert_not_awaited()
