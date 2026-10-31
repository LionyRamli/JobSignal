"""The only code that reads or writes JobSignal's tables.

Functions take a Session and never commit: the caller owns transaction boundaries
(the scrape CLI commits once per company so a later failure keeps earlier work).
"""

import math
from datetime import date, datetime
from typing import NamedTuple

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from jobsignal.harmonization.locations import LocationParse
from jobsignal.harmonization.roles import RoleClassification
from jobsignal.models import Posting
from jobsignal.storage.schema import (
    Company,
    Location,
    PostingRecord,
    ScrapeRun,
    SignalRun,
    SignalScore,
    Snapshot,
    posting_locations,
    snapshot_postings,
)
from jobsignal.storage.types import UTCDateTime


class StaleSnapshotError(Exception):
    """A snapshot older than the company's latest recorded one (overlapping runs)."""


def get_or_create_company(
    session: Session, source: str, board_token: str, now: datetime
) -> Company:
    company = session.scalar(
        select(Company).where(Company.source == source, Company.board_token == board_token)
    )
    if company is None:
        company = Company(source=source, board_token=board_token, created_at=now)
        session.add(company)
        session.flush()
    return company


def start_run(session: Session, now: datetime) -> ScrapeRun:
    run = ScrapeRun(started_at=now, status="running")
    session.add(run)
    session.flush()
    return run


def finish_run(session: Session, run: ScrapeRun, now: datetime) -> ScrapeRun:
    """Close the run; status: all snapshots ok → succeeded, none ok → failed, else partial."""
    session.flush()
    statuses = session.scalars(select(Snapshot.status).where(Snapshot.run_id == run.id)).all()
    ok = sum(status == "ok" for status in statuses)
    partial = sum(status == "partial" for status in statuses)
    if statuses and ok == len(statuses):
        run.status = "succeeded"
    elif ok == 0 and partial == 0:
        run.status = "failed"
    else:
        run.status = "partial"
    run.finished_at = now
    session.flush()
    return run


def record_snapshot(
    session: Session,
    run: ScrapeRun,
    company: Company,
    postings: list[Posting],
    fetched_at: datetime,
    complete: bool = True,
) -> Snapshot:
    """Record a successful fetch of ``company``'s board.

    ``complete=False`` (the source skipped malformed entries) records a ``partial``
    snapshot: seen postings are upserted and linked, but absent ones are NOT closed.
    Raises StaleSnapshotError if ``fetched_at`` predates the company's latest snapshot.

    Fetched postings are upserted (latest fields win), marked seen at ``fetched_at``, reopened
    if they had been closed, and linked to the snapshot. Open postings of this company that were
    not fetched are closed at ``fetched_at``. Nothing is written if any posting belongs elsewhere.
    """
    for posting in postings:
        if (posting.source, posting.company) != (company.source, company.board_token):
            raise ValueError(
                f"posting {posting.external_id!r} ({posting.source}/{posting.company}) "
                f"does not belong to {company.source}/{company.board_token}"
            )
    latest = session.scalar(
        select(func.max(Snapshot.fetched_at)).where(
            Snapshot.company_id == company.id, Snapshot.status.in_(("ok", "partial"))
        )
    )
    if latest is not None and fetched_at < latest:
        raise StaleSnapshotError(
            f"{company.source}/{company.board_token}: snapshot at {fetched_at.isoformat()} "
            f"is older than the latest one at {latest.isoformat()}"
        )

    fetched: dict[str, Posting] = {}
    for posting in postings:
        fetched.setdefault(posting.external_id, posting)  # first occurrence wins

    existing = {
        row.external_id: row
        for row in session.scalars(
            select(PostingRecord).where(PostingRecord.company_id == company.id)
        )
    }
    seen: list[PostingRecord] = []
    for external_id, posting in fetched.items():
        row = existing.get(external_id)
        if row is None:
            row = PostingRecord(
                company_id=company.id, external_id=external_id, first_seen_at=fetched_at
            )
            session.add(row)
        inputs = (posting.title, posting.location_raw, posting.department)
        if row.taxonomy_version is not None and inputs != (
            row.title,
            row.location_raw,
            row.department,
        ):
            row.taxonomy_version = None  # re-harmonize: classified inputs changed
        row.title = posting.title
        row.location_raw = posting.location_raw
        row.department = posting.department
        row.url = posting.url
        row.first_published = posting.first_published
        row.updated_at = posting.updated_at
        row.last_seen_at = fetched_at
        row.closed_at = None
        seen.append(row)

    # Closing in Python (rows already loaded) avoids SQLite's bound-parameter limit on NOT IN.
    # Only a complete fetch proves absence.
    if complete:
        for external_id, row in existing.items():
            if external_id not in fetched and row.closed_at is None:
                row.closed_at = fetched_at

    snapshot = Snapshot(
        run=run,
        company=company,
        fetched_at=fetched_at,
        status="ok" if complete else "partial",
        posting_count=len(fetched),
    )
    session.add(snapshot)
    session.flush()
    if seen:
        session.execute(
            insert(snapshot_postings),
            [{"snapshot_id": snapshot.id, "posting_id": row.id} for row in seen],
        )
    return snapshot


def record_failed_snapshot(
    session: Session, run: ScrapeRun, company: Company, error_type: str, fetched_at: datetime
) -> Snapshot:
    """Record a failed fetch. Postings are deliberately untouched: a failure is not a closure."""
    snapshot = Snapshot(
        run=run,
        company=company,
        fetched_at=fetched_at,
        status="failed",
        posting_count=None,
        error_type=error_type[:64],
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def open_postings(session: Session, company: Company) -> list[PostingRecord]:
    return list(
        session.scalars(
            select(PostingRecord)
            .where(PostingRecord.company_id == company.id, PostingRecord.closed_at.is_(None))
            .order_by(PostingRecord.external_id)
        )
    )


def postings_to_harmonize(session: Session, version: str, limit: int) -> list[PostingRecord]:
    """Postings never harmonized, or harmonized with a different taxonomy version (by id)."""
    return list(
        session.scalars(
            select(PostingRecord)
            .where(
                (PostingRecord.taxonomy_version.is_(None))
                | (PostingRecord.taxonomy_version != version)
            )
            .order_by(PostingRecord.id)
            .limit(limit)
        )
    )


def save_harmonization(
    session: Session,
    posting: PostingRecord,
    roles: RoleClassification,
    places: LocationParse,
    version: str,
    now: datetime,
) -> None:
    """Store role/seniority and REPLACE the posting's canonical locations."""
    posting.role_family = roles.family.value
    posting.seniority = roles.seniority.value
    posting.taxonomy_version = version
    posting.harmonized_at = now
    posting.locations = [_get_or_create_location(session, place) for place in places.locations]
    session.flush()


def _get_or_create_location(session: Session, place) -> Location:
    location = session.scalar(select(Location).where(Location.key == place.key))
    if location is None:
        location = Location(
            key=place.key,
            kind=place.kind.value,
            country_code=place.country_code,
            region_code=place.region_code,
            city=place.city,
        )
        session.add(location)
        session.flush()
    return location


class OpeningRow(NamedTuple):
    posting_id: int
    company: str
    role_family: str | None
    country_code: str | None
    first_seen_at: datetime
    first_published: datetime | None
    company_first_snapshot_at: datetime | None


def opening_rows(session: Session) -> list[OpeningRow]:
    """One row per posting and distinct located country (None when it has no country)."""
    first_snapshot = (
        select(Snapshot.company_id, func.min(Snapshot.fetched_at).label("first_at"))
        .where(Snapshot.status.in_(("ok", "partial")))
        .group_by(Snapshot.company_id)
        .subquery()
    )
    statement = (
        select(
            PostingRecord.id,
            Company.board_token,
            PostingRecord.role_family,
            Location.country_code,
            PostingRecord.first_seen_at,
            PostingRecord.first_published,
            first_snapshot.c.first_at,
        )
        .join(Company, Company.id == PostingRecord.company_id)
        .outerjoin(first_snapshot, first_snapshot.c.company_id == PostingRecord.company_id)
        .outerjoin(posting_locations, posting_locations.c.posting_id == PostingRecord.id)
        .outerjoin(Location, Location.id == posting_locations.c.location_id)
        .distinct()
        .order_by(PostingRecord.id)
    )
    utc = UTCDateTime()
    rows = []
    for pid, company, family, country, seen, published, first_at in session.execute(statement):
        # first_at comes from an aggregate, so the column type's conversion is not applied
        first_at = utc.process_result_value(_as_datetime(first_at), None)
        rows.append(OpeningRow(pid, company, family, country, seen, published, first_at))
    return rows


def ok_snapshot_stats(session: Session) -> dict[str, list[tuple[datetime, int, int]]]:
    """Company -> (fetched_at, posting_count, new_count) for every fully successful snapshot.

    new_count = postings first seen at that snapshot. signals.coverage turns these into the
    weeks whose new openings can be trusted (no outage gap, no re-import, no collapsed board).
    """
    new_by_time: dict[tuple[int, datetime], int] = {}
    for company_id, seen_at, n in session.execute(
        select(PostingRecord.company_id, PostingRecord.first_seen_at, func.count()).group_by(
            PostingRecord.company_id, PostingRecord.first_seen_at
        )
    ):
        new_by_time[
            (company_id, UTCDateTime().process_result_value(_as_datetime(seen_at), None))
        ] = n
    stats: dict[str, list[tuple[datetime, int, int]]] = {}
    statement = (
        select(
            Company.board_token, Snapshot.company_id, Snapshot.fetched_at, Snapshot.posting_count
        )
        .join(Company, Company.id == Snapshot.company_id)
        .where(Snapshot.status == "ok")
        .order_by(Snapshot.fetched_at)
    )
    for token, company_id, fetched_at, count in session.execute(statement):
        new = new_by_time.get((company_id, fetched_at), 0)
        stats.setdefault(token, []).append((fetched_at, int(count or 0), new))
    return stats


def _as_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


SCORE_FRAME_COLUMNS = frozenset(
    {
        "detector", "basis", "level", "company", "role_family", "country", "week_start",
        "observed", "baseline_mean", "baseline_std", "baseline_weeks", "z", "status",
        "is_signal", "direction", "severity", "company_recent_total", "company_baseline_total",
    }
)  # fmt: skip


def _nullable(value):
    """pandas stores missing values as NaN/NaT/None; the database wants NULL."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "date") and not isinstance(value, date):  # pandas Timestamp
        return value.date()
    return value


def save_signal_run(
    session: Session, computed_at: datetime, as_of: datetime, params, scores
) -> SignalRun:
    """Validate, then store one run and all its scores (append-only).

    ``scores`` is a DataFrame with exactly SCORE_FRAME_COLUMNS. A z that is not finite is
    allowed only for ``insufficient_history`` rows (stored as NULL); anywhere else it raises
    before anything is written.
    """
    from jobsignal.harmonization.taxonomy import TAXONOMY_VERSION
    from jobsignal.signals.params import SIGNALS_VERSION

    if set(scores.columns) != SCORE_FRAME_COLUMNS:
        missing = sorted(SCORE_FRAME_COLUMNS - set(scores.columns))
        extra = sorted(set(scores.columns) - SCORE_FRAME_COLUMNS)
        raise ValueError(f"score frame columns differ: missing={missing} extra={extra}")

    company_ids: dict[str, int] = {}
    for token, company_id in session.execute(select(Company.board_token, Company.id)):
        if token in company_ids:
            raise ValueError(f"board token {token!r} is ambiguous across sources")
        company_ids[token] = company_id

    rows = []
    for record in scores.to_dict(orient="records"):
        z = _nullable(record["z"])
        if record["status"] != "insufficient_history" and (z is None or not math.isfinite(z)):
            raise ValueError(f"z must be finite for {record['status']} rows, got {record['z']!r}")
        if z is not None and not math.isfinite(z):
            raise ValueError(f"z must be finite or NULL, got {z!r}")
        if record["company"] not in company_ids:
            raise ValueError(f"unknown company {record['company']!r}")
        rows.append(
            {
                "detector": record["detector"],
                "basis": record["basis"],
                "level": record["level"],
                "company_id": company_ids[record["company"]],
                "role_family": _nullable(record["role_family"]),
                "country_code": _nullable(record["country"]),
                "week_start": _as_date(record["week_start"]),
                "observed": float(record["observed"]),
                "baseline_mean": _nullable(record["baseline_mean"]),
                "baseline_std": _nullable(record["baseline_std"]),
                "baseline_weeks": int(record["baseline_weeks"]),
                "z": z,
                "status": record["status"],
                "is_signal": bool(record["is_signal"]),
                "direction": _nullable(record["direction"]),
                "severity": _nullable(record["severity"]),
                "company_recent_total": _nullable(record["company_recent_total"]),
                "company_baseline_total": _nullable(record["company_baseline_total"]),
            }
        )

    run = SignalRun(
        computed_at=computed_at,
        as_of=as_of,
        signals_version=SIGNALS_VERSION,
        taxonomy_version=TAXONOMY_VERSION,
        params=params.to_json(),
    )
    session.add(run)
    session.flush()
    if rows:
        session.execute(insert(SignalScore), [{"run_id": run.id, **row} for row in rows])
    return run


def latest_signals(session: Session, limit: int = 50) -> list[SignalScore]:
    """Signals of the run with the newest ``as_of``, strongest first (by |z|).

    Ordering by as_of (not computed_at) means a backtest run computed later for an older
    week never hides the live run.
    """
    newest = session.scalar(
        select(SignalRun.id)
        .order_by(SignalRun.as_of.desc(), SignalRun.computed_at.desc(), SignalRun.id.desc())
        .limit(1)
    )
    if newest is None:
        return []
    return list(
        session.scalars(
            select(SignalScore)
            .where(SignalScore.run_id == newest, SignalScore.is_signal.is_(True))
            .order_by(func.abs(SignalScore.z).desc(), SignalScore.id)
            .limit(limit)
        )
    )
