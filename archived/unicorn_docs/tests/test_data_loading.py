"""Tests for the Markdown keyword-index loader."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from unicorn_docs.unicorndocs_precomputed import UnicornDocsPrecomputed


def test_workflow_documents_keyword_index_without_pickle_pipeline() -> None:
    workflow = (Path(__file__).resolve().parents[1] / "WORKFLOW.md").read_text(encoding="utf-8")
    assert "deterministic keyword retrieval" in workflow
    assert "indexer_local_standalone.py" not in workflow
    assert "pip install sentence-transformers" not in workflow


def make_cog() -> UnicornDocsPrecomputed:
    config = MagicMock(spec=Config)
    with patch("unicorn_docs.unicorndocs_precomputed.Config.get_conf", return_value=config):
        return UnicornDocsPrecomputed(MagicMock(spec=Red))


def test_load_data_sync_indexes_markdown(tmp_path: Path) -> None:
    cog = make_cog()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# Rules\n\nDo not spam.\n\nBe respectful.", encoding="utf-8")

    config, metadata = cog._load_data_sync(docs)

    assert config == {"retrieval": "keyword", "total_files": 1}
    assert metadata
    assert metadata[0]["source_file"] == "rules.md"
    assert "spam" in metadata[0]["original_text"]


def test_load_data_sync_missing_docs_raises(tmp_path: Path) -> None:
    cog = make_cog()
    with pytest.raises(FileNotFoundError, match="Documentation directory"):
        cog._load_data_sync(tmp_path / "missing")


def test_load_data_sync_ignores_legacy_pickle_files(tmp_path: Path) -> None:
    cog = make_cog()
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "metadata.pkl").write_bytes(b"not a trusted pickle")
    (docs / "safe.md").write_text("trusted markdown", encoding="utf-8")

    _, metadata = cog._load_data_sync(docs)

    assert [item["original_text"] for item in metadata] == ["trusted markdown"]
