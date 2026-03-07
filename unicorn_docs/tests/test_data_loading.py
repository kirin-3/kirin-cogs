"""Unit tests for _load_data_sync in unicorn_docs."""

import json
import pickle
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from unicorn_docs.unicorndocs_precomputed import UnicornDocsPrecomputed


def make_cog() -> UnicornDocsPrecomputed:
    config = MagicMock(spec=Config)
    config.register_global = MagicMock()

    bot = MagicMock(spec=Red)
    bot.loop = MagicMock()

    with patch("unicorn_docs.unicorndocs_precomputed.Config.get_conf", return_value=config):
        cog = UnicornDocsPrecomputed(bot)  # type: ignore[arg-type]
    cog.config = config
    return cog


def test_load_data_sync_all_files_present(tmp_path: Path) -> None:
    """_load_data_sync loads config, embeddings, and metadata correctly."""
    cog = make_cog()

    # Create test vectors directory
    vectors = tmp_path / "vectors"
    vectors.mkdir()

    config_data = {"embedding_model": "test", "total_files": 1}
    embeddings_data = [[0.1, 0.2], [0.3, 0.4]]
    metadata_data = [{"original_text": "hello", "source_file": "a.md"}]

    with open(vectors / "config.json", "w") as f:
        json.dump(config_data, f)

    with open(vectors / "embeddings.pkl", "wb") as f:
        pickle.dump(embeddings_data, f)

    with open(vectors / "metadata.pkl", "wb") as f:
        pickle.dump(metadata_data, f)

    config, embeddings, metadata = cog._load_data_sync(vectors)

    assert config["embedding_model"] == "test"
    assert embeddings == embeddings_data
    assert metadata == metadata_data


def test_load_data_sync_missing_embeddings_raises(tmp_path: Path) -> None:
    """Missing embeddings.pkl should raise FileNotFoundError."""
    cog = make_cog()

    vectors = tmp_path / "vectors"
    vectors.mkdir()

    # Only config and metadata, no embeddings
    with open(vectors / "config.json", "w") as f:
        json.dump({}, f)

    with open(vectors / "metadata.pkl", "wb") as f:
        pickle.dump([], f)

    with pytest.raises(FileNotFoundError, match="Embeddings"):
        cog._load_data_sync(vectors)


def test_load_data_sync_missing_config_returns_empty_dict(tmp_path: Path) -> None:
    """Missing config.json should result in empty config dict, not an error."""
    cog = make_cog()

    vectors = tmp_path / "vectors"
    vectors.mkdir()

    with open(vectors / "embeddings.pkl", "wb") as f:
        pickle.dump([[0.1], [0.2]], f)

    with open(vectors / "metadata.pkl", "wb") as f:
        pickle.dump([{"original_text": "x", "source_file": "x.md"}], f)

    config, embeddings, _metadata = cog._load_data_sync(vectors)

    assert config == {}
    assert len(embeddings) == 2
