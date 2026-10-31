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


class LocationOut(BaseModel):
    key: str
    kind: str
    country_code: str | None
    region_code: str | None
    city: str | None


class PostingOut(BaseModel):
    id: int
    company: str
    external_id: str
    title: str
    department: str | None
    location_raw: str | None
    url: str
    role_family: str | None
    seniority: str | None
    locations: list[LocationOut]
    first_published: UTC_DATETIME | None
    first_seen_at: UTC_DATETIME
    last_seen_at: UTC_DATETIME
    closed_at: UTC_DATETIME | None

    @classmethod
    def from_record(cls, row) -> "PostingOut":
        return cls(
            id=row.id,
            company=row.company.board_token,
            external_id=row.external_id,
            title=row.title,
            department=row.department,
            location_raw=row.location_raw,
            url=row.url,
            role_family=row.role_family,
            seniority=row.seniority,
            locations=[
                LocationOut.model_validate(loc, from_attributes=True) for loc in row.locations
            ],
            first_published=row.first_published,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            closed_at=row.closed_at,
        )


class PostingsPage(BaseModel):
    items: list[PostingOut]
    next_cursor: str | None
