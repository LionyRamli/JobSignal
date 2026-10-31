"""Response models: the API's JSON contract (separate from the ORM)."""

import json
import math
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

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


class SignalRunOut(BaseModel):
    id: int
    computed_at: UTC_DATETIME
    as_of: UTC_DATETIME
    signals_version: str
    taxonomy_version: str
    params: dict[str, Any]

    @classmethod
    def from_record(cls, run) -> "SignalRunOut":
        return cls(
            id=run.id,
            computed_at=run.computed_at,
            as_of=run.as_of,
            signals_version=run.signals_version,
            taxonomy_version=run.taxonomy_version,
            params=json.loads(run.params),
        )


def _share(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


class SignalOut(BaseModel):
    """One stored score. Raw values are always present. For mix_shift, observed and
    baseline_mean are cell TOTALS and share_recent / share_baseline are the comparable shares."""

    id: int
    run_id: int
    detector: str
    basis: str
    level: str
    company: str
    role_family: str | None
    country_code: str | None
    week_start: date
    observed: FiniteFloat
    baseline_mean: FiniteFloat
    baseline_std: FiniteFloat
    baseline_weeks: int
    z: FiniteFloat
    status: str
    is_signal: bool
    direction: str | None
    severity: str | None
    share_recent: FiniteFloat
    share_baseline: FiniteFloat
    provisional: bool  # published-date basis: survivorship-biased

    @classmethod
    def from_record(cls, score, company: str) -> "SignalOut":
        mix = score.detector == "mix_shift"
        return cls(
            id=score.id,
            run_id=score.run_id,
            detector=score.detector,
            basis=score.basis,
            level=score.level,
            company=company,
            role_family=score.role_family,
            country_code=score.country_code,
            week_start=score.week_start,
            observed=score.observed,
            baseline_mean=score.baseline_mean,
            baseline_std=score.baseline_std,
            baseline_weeks=score.baseline_weeks,
            z=score.z,
            status=score.status,
            is_signal=score.is_signal,
            direction=score.direction,
            severity=score.severity,
            share_recent=_share(score.observed, score.company_recent_total) if mix else None,
            share_baseline=(
                _share(score.baseline_mean, score.company_baseline_total) if mix else None
            ),
            provisional=score.basis == "published",
        )


class SignalsPage(BaseModel):
    run: SignalRunOut | None
    items: list[SignalOut]


class PostingBrief(BaseModel):
    id: int
    title: str
    url: str
    locations: list[LocationOut]


class SignalDetail(BaseModel):
    signal: SignalOut
    run: SignalRunOut
    postings: list[PostingBrief]
