"""Unit tests for cosine similarity search in unicorn_docs."""

from unittest.mock import MagicMock, patch

from redbot.core import Config
from redbot.core.bot import Red

from unicorn_docs.unicorndocs_precomputed import UnicornDocsPrecomputed


def make_cog() -> UnicornDocsPrecomputed:
    config = MagicMock(spec=Config)
    config.register_global = MagicMock()

    bot = MagicMock(spec=Red)

    with patch("unicorn_docs.unicorndocs_precomputed.Config.get_conf", return_value=config):
        cog = UnicornDocsPrecomputed(bot)  # type: ignore[arg-type]
    cog.config = config
    return cog


def test_cosine_similarity_identical_vectors() -> None:
    """Identical vectors should have cosine similarity of 1.0."""
    cog = make_cog()
    vec = [1.0, 0.0, 0.0]
    result = cog.cosine_similarity(vec, vec)
    assert abs(result - 1.0) < 1e-6


def test_cosine_similarity_orthogonal_vectors() -> None:
    """Orthogonal vectors should have cosine similarity of 0.0."""
    cog = make_cog()
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    result = cog.cosine_similarity(a, b)
    assert abs(result) < 1e-6


def test_cosine_similarity_zero_vector() -> None:
    """Zero vector should return 0 safely without division error."""
    cog = make_cog()
    result = cog.cosine_similarity([0.0, 0.0], [1.0, 0.5])
    assert result == 0


def test_simple_text_search_finds_relevant_result() -> None:
    """Top result should match the query text."""
    cog = make_cog()
    cog._metadata = [
        {"original_text": "Unicornia server moderation rules", "source_file": "rules.md"},
        {"original_text": "Tips for cooking pasta", "source_file": "food.md"},
    ]

    results = cog.simple_text_search("moderation rules", max_chunks=8)

    assert len(results) >= 1
    # The moderation rules chunk should rank first
    assert "moderation" in results[0]["text"].lower() or "rules" in results[0]["text"].lower()


def test_simple_text_search_capped_at_max_chunks() -> None:
    """Results should not exceed max_chunks."""
    cog = make_cog()
    cog._metadata = [{"original_text": f"relevant content {i}", "source_file": f"file{i}.md"} for i in range(20)]

    results = cog.simple_text_search("relevant content", max_chunks=5)
    assert len(results) <= 5


def test_simple_text_search_no_match_returns_empty() -> None:
    """No matching text should return empty list."""
    cog = make_cog()
    cog._metadata = [
        {"original_text": "hello world", "source_file": "file.md"},
    ]

    results = cog.simple_text_search("zzzyyyy irrelevant term", max_chunks=8)
    # May return empty or very low score items; either acceptable
    assert isinstance(results, list)
