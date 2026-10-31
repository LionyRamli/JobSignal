"""Response models: the API's JSON contract (separate from the ORM)."""

import math
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, PlainSerializer


def _utc_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _finite(value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise ValueError("non-finite float")  # NaN/Infinity are not valid JSON
    return value


UTC_DATETIME = Annotated[datetime, PlainSerializer(_utc_z, return_type=str)]
FiniteFloat = Annotated[float | None, AfterValidator(_finite)]


class Health(BaseModel):
    status: Literal["ok", "schema_missing"]
    taxonomy_version: str
    signals_version: str


class Meta(BaseModel):
    role_families: list[str]
    seniorities: list[str]
    location_kinds: list[str]
    signal_levels: list[str]
    detectors: list[str]
    taxonomy_version: str
    signals_version: str


class Company(BaseModel):
    board_token: str
    source: str
    open_postings: int
    last_snapshot_at: UTC_DATETIME | None
    last_snapshot_status: str | None
