"""The only code that reads or writes JobSignal's tables.

Functions take a Session and never commit: the caller owns transaction boundaries
(the scrape CLI commits once per company so a later failure keeps earlier work).
"""

from datetime import datetime

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
    Snapshot,
    snapshot_postings,
)


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
