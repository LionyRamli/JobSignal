import logging
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Keep every test independent of the developer's shell env and local .env file."""
    for key in list(os.environ):
        if key.startswith("JOBSIGNAL_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def reset_package_logger():
    """Undo any setup_logging() a test triggered, so handlers never leak across tests."""
    yield
    pkg = logging.getLogger("jobsignal")
    for handler in list(pkg.handlers):
        pkg.removeHandler(handler)
        handler.close()
    pkg.setLevel(logging.NOTSET)
    pkg.propagate = True
