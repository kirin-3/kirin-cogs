"""Shared fixtures for unicorn_docs tests."""

import json
import pickle
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redbot.core import Config
from redbot.core.bot import Red

from unicorn_docs.unicorndocs_precomputed import UnicornDocsPrecomputed


@pytest.fixture
def config_mock() -> MagicMock:
    config = MagicMock(spec=Config)
    config.openrouter_api_key = AsyncMock(return_value="test-key")
    config.openrouter_api_key.set = AsyncMock()
    config.register_global = MagicMock()
    return config


@pytest.fixture
def bot_mock() -> MagicMock:
    bot = MagicMock(spec=Red)
    bot.loop = MagicMock()
    bot.loop.run_in_executor = AsyncMock(return_value=({"version": "1"}, [], []))
    return bot


@pytest.fixture
def cog(bot_mock: MagicMock, config_mock: MagicMock) -> UnicornDocsPrecomputed:
    with patch("unicorn_docs.unicorndocs_precomputed.Config.get_conf", return_value=config_mock):
        instance = UnicornDocsPrecomputed(bot_mock)  # type: ignore[arg-type]
    instance.config = config_mock
    return instance


@pytest.fixture
def tmp_vectors_path(tmp_path: Path) -> Path:
    """Fixture that creates minimal vectors directory with required files."""
    vectors_path = tmp_path / "vectors"
    vectors_path.mkdir()

    # Minimal config
    config = {"embedding_model": "test-model", "total_files": 1}
    with open(vectors_path / "config.json", "w") as f:
        json.dump(config, f)

    # Minimal embeddings and metadata
    embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    metadata = [
        {"original_text": "Unicornia server rules", "source_file": "rules.md"},
        {"original_text": "Moderation guidelines", "source_file": "guidelines.md"},
    ]

    with open(vectors_path / "embeddings.pkl", "wb") as f:
        pickle.dump(embeddings, f)

    with open(vectors_path / "metadata.pkl", "wb") as f:
        pickle.dump(metadata, f)

    return vectors_path
