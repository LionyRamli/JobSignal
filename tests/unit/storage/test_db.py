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


def test_session_factory_does_not_expire_on_commit(tmp_path):
    from sqlalchemy import Column, Integer, String, event
    from sqlalchemy.orm import DeclarativeBase

    from jobsignal.storage.db import make_session_factory

    class TestBase(DeclarativeBase):
        pass

    class Thing(TestBase):
        __tablename__ = "things"
        id = Column(Integer, primary_key=True)
        name = Column(String)

    engine = make_engine(f"sqlite:///{(tmp_path / 's.db').as_posix()}")
    TestBase.metadata.create_all(engine)
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *args: statements.append(args[2]))

    with make_session_factory(engine)() as session:
        thing = Thing(name="acme")
        session.add(thing)
        session.commit()
        statements.clear()
        assert thing.name == "acme"

    assert statements == []
