# Reuse the SimCord-backed Red fixtures from python-bot (it must be on PYTHONPATH), but load cogs
# from tools/ instead of python-bot/.
from pathlib import Path

import pytest

import testutils.red
from testutils.red import red_env, simcord_bot  # noqa: F401


@pytest.fixture(autouse=True)
def _cogs_from_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(testutils.red, "REPO_ROOT", Path(__file__).resolve().parents[2])
