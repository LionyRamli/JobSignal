from sqlalchemy import text

from jobsignal.storage.db import make_engine


def test_engine_uses_configured_database_url(monkeypatch, tmp_path):
    db_file = tmp_path / "configured.db"
    monkeypatch.setenv("JOBSIGNAL_DATABASE_URL", f"sqlite:///{db_file.as_posix()}")

    engine = make_engine()

    assert engine.url.database == db_file.as_posix()


def test_explicit_url_wins_over_settings(monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_DATABASE_URL", "sqlite:///from_env.db")

    engine = make_engine("sqlite:///explicit.db")

    assert engine.url.database == "explicit.db"


def test_sqlite_connections_enforce_foreign_keys(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'fk.db').as_posix()}")

    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
