"""FastAPI application factory. Read-only: every route is GET under /api/v1.

uv run python scripts/run_api.py [--host 127.0.0.1] [--port 8000]
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI

from jobsignal.api.deps import require_schema
from jobsignal.api.routes import companies, health, meta, postings
from jobsignal.config import get_settings
from jobsignal.storage.db import make_engine, make_session_factory

API_PREFIX = "/api/v1"


def create_app(database_url: str | None = None) -> FastAPI:
    url = database_url or get_settings().database_url

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(url)
        app.state.sessions = make_session_factory(app.state.engine)
        try:
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(title="JobSignal API", version="1.0.0", lifespan=lifespan)
    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    data = APIRouter(dependencies=[Depends(require_schema)])
    for module in (meta, companies, postings):
        data.include_router(module.router)
    api.include_router(data)
    app.include_router(api)
    return app
