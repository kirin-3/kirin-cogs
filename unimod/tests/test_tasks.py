import asyncio
from unittest.mock import MagicMock, patch

import pytest

from unimod.unimod import UniMod


@pytest.fixture
def cog():
    bot = MagicMock()
    with patch("unimod.unimod.Config.get_conf"), patch("discord.ext.tasks.Loop.start"):
        return UniMod(bot)


@pytest.mark.asyncio
async def test_task_unload(cog: UniMod):
    dummy_task = asyncio.create_task(asyncio.sleep(10))
    cog._background_tasks.add(dummy_task)

    # Run cog unload
    await cog.cog_unload()

    # Task should be cancelled
    assert dummy_task.cancelled() or dummy_task.done()


@pytest.mark.asyncio
async def test_event_loop_responsiveness(cog: UniMod):
    import time

    start = time.time()
    await cog.cog_load()
    assert time.time() - start < 1.0  # Should be fast and not block event loop
