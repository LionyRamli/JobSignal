"""Request-scoped dependencies: one SQLAlchemy session per request, schema guard."""

from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from jobsignal.storage.db import schema_ready

SCHEMA_MISSING = "database schema missing; run: uv run alembic upgrade head"


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessions() as session:
        yield session


def require_schema(request: Request) -> None:
    if not schema_ready(request.app.state.engine):
        raise HTTPException(status_code=503, detail=SCHEMA_MISSING)


def get_now() -> datetime:
    """The request's clock (overridable in tests via app.dependency_overrides)."""
    return datetime.now(UTC)
