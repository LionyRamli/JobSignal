"""Shared fixtures: a real SQLite file under tmp_path, migrated with Alembic."""

import pytest
from alembic import command
from alembic.config import Config

from jobsignal.storage.db import make_engine, make_session_factory
from tests.conftest import PROJECT_ROOT


@pytest.fixture
def db_url(monkeypatch, tmp_path):
    url = f"sqlite:///{(tmp_path / 'jobsignal-test.db').as_posix()}"
    monkeypatch.setenv("JOBSIGNAL_DATABASE_URL", url)
    return url


@pytest.fixture
def alembic_cfg():
    return Config(str(PROJECT_ROOT / "alembic.ini"))


@pytest.fixture
def migrated_url(alembic_cfg, db_url):
    command.upgrade(alembic_cfg, "head")
    return db_url


@pytest.fixture
def session(migrated_url):
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as s:
        yield s
    engine.dispose()
