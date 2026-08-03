import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from unimod.unimod import UniMod


@pytest.fixture
def cog() -> UniMod:
    bot = MagicMock()
    with patch("unimod.unimod.Config.get_conf"), patch("discord.ext.tasks.Loop.start"):
        return UniMod(bot)


def test_diagnostic_retention_and_redaction(cog: UniMod, tmp_path: Path) -> None:
    module_path = tmp_path / "unimod.py"
    log_path = tmp_path / "last.log"
    with patch("unimod.unimod.Path", return_value=module_path):
        cog._save_last_response("disabled 123456789012345678")
        assert not log_path.exists()

        cog.diagnostic_mode = True
        cog.diagnostic_expiry = time.time() + 3600
        cog._save_last_response("user 123456789012345678")
        saved = log_path.read_text(encoding="utf-8")
        assert "123456789012345678" not in saved
        assert "[discord-id]" in saved

        cog.diagnostic_expiry = time.time() - 1
        cog._save_last_response("expired")
        assert not log_path.exists()
        assert cog.diagnostic_mode is False
