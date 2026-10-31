from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from jobsignal.api.schemas import Health
from jobsignal.harmonization.taxonomy import TAXONOMY_VERSION
from jobsignal.signals.params import SIGNALS_VERSION
from jobsignal.storage.db import schema_ready

router = APIRouter(tags=["health"])


@router.get("/health", response_model=Health, responses={503: {"model": Health}})
def health(request: Request):
    ready = schema_ready(request.app.state.engine)
    body = Health(
        status="ok" if ready else "schema_missing",
        taxonomy_version=TAXONOMY_VERSION,
        signals_version=SIGNALS_VERSION,
    )
    return body if ready else JSONResponse(status_code=503, content=body.model_dump())
