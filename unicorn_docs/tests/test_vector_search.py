"""Unit tests for documented keyword retrieval in UnicornDocs."""

from unittest.mock import MagicMock, patch

from redbot.core import Config
from redbot.core.bot import Red

from unicorn_docs.unicorndocs_precomputed import UnicornDocsPrecomputed


def make_cog() -> UnicornDocsPrecomputed:
    config = MagicMock(spec=Config)
    with patch("unicorn_docs.unicorndocs_precomputed.Config.get_conf", return_value=config):
        return UnicornDocsPrecomputed(MagicMock(spec=Red))


def test_simple_text_search_finds_relevant_result() -> None:
    cog = make_cog()
    cog._metadata = [
        {"original_text": "Unicornia server moderation rules", "source_file": "rules.md"},
        {"original_text": "Tips for cooking pasta", "source_file": "food.md"},
    ]

    results = cog.simple_text_search("moderation rules", max_chunks=8)

    assert results[0]["source_file"] == "rules.md"


def test_simple_text_search_capped_at_max_chunks() -> None:
    cog = make_cog()
    cog._metadata = [{"original_text": f"relevant content {i}", "source_file": f"file{i}.md"} for i in range(20)]
    assert len(cog.simple_text_search("relevant content", max_chunks=5)) == 5


def test_simple_text_search_no_match_returns_empty() -> None:
    cog = make_cog()
    cog._metadata = [{"original_text": "hello world", "source_file": "file.md"}]
    assert cog.simple_text_search("zzzyyyy", max_chunks=8) == []
