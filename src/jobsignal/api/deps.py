"""Request-scoped dependencies: one SQLAlchemy session per request, schema guard."""

from collections.abc import Iterator

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
