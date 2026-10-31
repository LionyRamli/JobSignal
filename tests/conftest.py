from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Keep every test independent of the developer's shell env and local .env file."""
    import os

    for key in list(os.environ):
        if key.startswith("JOBSIGNAL_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
