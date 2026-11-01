"""FastAPI application factory. Read-only: every route is GET under /api/v1.

uv run python scripts/run_api.py [--host 127.0.0.1] [--port 8000]
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from jobsignal.api.deps import require_schema
from jobsignal.api.routes import companies, health, meta, postings, signals
from jobsignal.api.security import api_key_dependency
from jobsignal.config import get_settings
from jobsignal.storage.db import make_engine, make_session_factory

API_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)


def create_app(database_url: str | None = None) -> FastAPI:
    settings = get_settings()
    url = database_url or settings.database_url

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
    data = APIRouter(
        dependencies=[Depends(api_key_dependency(settings.api_key)), Depends(require_schema)]
    )
    for module in (meta, companies, postings, signals):
        data.include_router(module.router)
    api.include_router(data)
    app.include_router(api)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        # never leak stack traces, paths or exception text to clients
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET"]
        )
    return app
