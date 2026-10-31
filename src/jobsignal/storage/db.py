"""Engine factory. The only place that knows how to connect to the database."""

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from jobsignal.config import get_settings


def make_engine(url: str | None = None) -> Engine:
    """Create an engine for ``url``, defaulting to the configured ``database_url``."""
    engine = create_engine(url or get_settings().database_url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sessions whose objects stay readable after commit (the CLI logs them post-commit)."""
    return sessionmaker(bind=engine, expire_on_commit=False)


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    # SQLite ignores FOREIGN KEY constraints unless enabled per connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
