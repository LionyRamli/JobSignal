"""The only code that reads or writes JobSignal's tables.

Functions take a Session and never commit: the caller owns transaction boundaries
(the scrape CLI commits once per company so a later failure keeps earlier work).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobsignal.storage.schema import Company, ScrapeRun, Snapshot


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
    if statuses and ok == len(statuses):
        run.status = "succeeded"
    elif ok == 0:
        run.status = "failed"
    else:
        run.status = "partial"
    run.finished_at = now
    session.flush()
    return run
