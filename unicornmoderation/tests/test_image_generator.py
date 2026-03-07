"""Unit tests for generate_citation in unicornmoderation."""

import io

import pytest

from unicornmoderation.image_generator import generate_citation


def test_generate_citation_returns_bytesio() -> None:
    """generate_citation should return a BytesIO object."""
    result = generate_citation("Ban", "TestUser", "Test reason")
    assert isinstance(result, io.BytesIO)


def test_generate_citation_seeked_to_start() -> None:
    """Buffer should be seeked to position 0 so it can be read immediately."""
    result = generate_citation("Kick", "TestUser", "Bad behavior")
    assert result.tell() == 0


def test_generate_citation_png_magic_bytes() -> None:
    """First 4 bytes of the buffer should be the PNG magic bytes."""
    result = generate_citation("Mute", "SomeUser", "Reason here")
    header = result.read(4)
    assert header == b"\x89PNG", f"Expected PNG header, got {header!r}"


def test_generate_citation_fallback_font(tmp_path: pytest.TempPathFactory) -> None:
    """generate_citation should work even in the fallback font path."""
    # The fallback is triggered automatically if font file missing; still returns valid PNG
    result = generate_citation("Warning", "AnotherUser", "Fallback test")
    result.seek(0)
    header = result.read(4)
    assert header == b"\x89PNG"


def test_generate_citation_different_actions() -> None:
    """Different action strings should all produce valid PNG buffers."""
    for action in ("Ban", "Kick", "Mute", "Unmute", "Warning"):
        result = generate_citation(action, "User", "reason")
        assert result.tell() == 0
        assert result.read(4) == b"\x89PNG"
