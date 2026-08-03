"""Unit tests for _get_buffer and _get_lock in unimod."""

import asyncio
from collections import deque
from unittest.mock import MagicMock, patch

import pytest

from unimod.unimod import BufferedMessage, UniMod


def make_cog() -> UniMod:
    bot = MagicMock()
    with patch("unimod.unimod.Config.get_conf"), patch("discord.ext.tasks.Loop.start"):
        return UniMod(bot)  # type: ignore[arg-type]


def test_get_buffer_creates_on_first_call() -> None:
    cog = make_cog()
    buf = cog._get_buffer(channel_id=999)
    assert isinstance(buf, deque)
    assert buf.maxlen == 20  # default max_size


def test_get_buffer_returns_same_instance() -> None:
    cog = make_cog()
    buf1 = cog._get_buffer(channel_id=111)
    buf2 = cog._get_buffer(channel_id=111)
    assert buf1 is buf2


def test_get_buffer_different_channels_have_separate_buffers() -> None:
    cog = make_cog()
    buf1 = cog._get_buffer(channel_id=1)
    buf2 = cog._get_buffer(channel_id=2)
    assert buf1 is not buf2


def test_get_buffer_custom_max_size() -> None:
    cog = make_cog()
    buf = cog._get_buffer(channel_id=777, max_size=5)
    assert buf.maxlen == 5


def test_get_lock_creates_on_first_call() -> None:
    cog = make_cog()
    lock = cog._get_lock(channel_id=999)
    assert isinstance(lock, asyncio.Lock)


def test_get_lock_returns_same_instance() -> None:
    cog = make_cog()
    lock1 = cog._get_lock(channel_id=111)
    lock2 = cog._get_lock(channel_id=111)
    assert lock1 is lock2


def test_get_lock_different_channels_have_separate_locks() -> None:
    cog = make_cog()
    lock1 = cog._get_lock(channel_id=1)
    lock2 = cog._get_lock(channel_id=2)
    assert lock1 is not lock2


def test_buffer_resize() -> None:
    cog = make_cog()
    buf = cog._get_buffer(channel_id=999)
    for i in range(25):
        buf.append(i)
    assert len(buf) == 20
    assert buf[0] == 5
    new_buf = deque(buf, maxlen=10)
    assert len(new_buf) == 10
    assert new_buf[0] == 15


@pytest.mark.asyncio
async def test_user_deletion_removes_only_matching_buffer_messages() -> None:
    cog = make_cog()
    buffer = cog._get_buffer(channel_id=999)
    for message_id, author_id in ((1, 42), (2, 99), (3, 42)):
        buffer.append(
            BufferedMessage(
                id=message_id,
                author_id=author_id,
                author_name="User",
                content="content",
                timestamp="now",
                channel_id=999,
                channel_name="test",
                guild_id=1,
            )
        )

    await cog.red_delete_data_for_user(requester="user", user_id=42)

    assert [message.author_id for message in cog.channel_buffers[999]] == [99]
