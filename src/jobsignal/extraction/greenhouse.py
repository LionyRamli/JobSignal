"""Greenhouse public job-board source (``boards-api.greenhouse.io``).

Uses ``/v1/boards/{token}/departments``: one request returns every open job grouped by
department (~0.5 MB for 675 jobs), versus ``/jobs?content=true`` (~10 MB) which is the
only other way to get departments.
"""

import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError

from jobsignal.extraction.base import ATSSource
from jobsignal.extraction.errors import InvalidPayloadError
from jobsignal.extraction.http_client import HttpClient
from jobsignal.models import Posting

logger = logging.getLogger(__name__)

API_BASE = "https://boards-api.greenhouse.io/v1/boards"
BOARD_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
NO_DEPARTMENT_ID = 0


class _Location(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str | None = None


class _GreenhouseJob(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    title: str
    absolute_url: str
    location: _Location | None = None
    first_published: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class _Department(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    name: str | None = None
    jobs: list[Any] | None = None  # elements validated one by one in _to_posting


class _DepartmentsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    departments: list[_Department]


class GreenhouseSource(ATSSource):
    name = "greenhouse"

    def __init__(
        self, http: HttpClient, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._http = http
        self._clock = clock

    def fetch_postings(self, company: str) -> list[Posting]:
        if not BOARD_TOKEN_RE.fullmatch(company):
            raise ValueError(f"invalid Greenhouse board token: {company!r}")

        logger.info("fetch started source=greenhouse company=%s", company)
        raw = self._http.get_json(f"{API_BASE}/{company}/departments")
        try:
            payload = _DepartmentsPayload.model_validate(raw)
        except ValidationError as exc:
            raise InvalidPayloadError(
                f"unexpected Greenhouse payload for {company!r}: {exc.error_count()} errors"
            ) from exc

        fetched_at = self._clock()
        postings: list[Posting] = []
        seen: set[str] = set()
        for department in payload.departments:
            if department.jobs is None:
                logger.warning(
                    "skipping department without job list company=%s department_id=%d",
                    company,
                    department.id,
                )
                continue
            department_name = None if department.id == NO_DEPARTMENT_ID else department.name
            for job in department.jobs:
                posting = self._to_posting(job, company, department_name, fetched_at)
                if posting is None or posting.external_id in seen:
                    continue
                seen.add(posting.external_id)
                postings.append(posting)

        logger.info(
            "fetch finished source=greenhouse company=%s postings=%d", company, len(postings)
        )
        return postings

    def _to_posting(
        self, job: Any, company: str, department: str | None, fetched_at: datetime
    ) -> Posting | None:
        if not isinstance(job, dict):
            logger.warning(
                "skipping non-object job entry company=%s type=%s", company, type(job).__name__
            )
            return None
        try:
            parsed = _GreenhouseJob.model_validate(job)
            return Posting(
                source=self.name,
                company=company,
                external_id=str(parsed.id),
                title=parsed.title,
                location_raw=parsed.location.name if parsed.location else None,
                department=department,
                url=parsed.absolute_url,
                first_published=parsed.first_published,
                updated_at=parsed.updated_at,
                fetched_at=fetched_at,
            )
        except ValidationError as exc:
            logger.warning(
                "skipping malformed job company=%s job_id=%r errors=%d",
                company,
                job.get("id", "?"),
                exc.error_count(),
            )
            return None
