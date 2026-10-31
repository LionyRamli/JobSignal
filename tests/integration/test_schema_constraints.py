from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from jobsignal.storage.schema import (
    RUN_STATUSES,
    SNAPSHOT_STATUSES,
    Company,
    PostingRecord,
    ScrapeRun,
    Snapshot,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def company(slug="anthropic"):
    return Company(source="greenhouse", board_token=slug, created_at=NOW)


def posting(company_obj, external_id="1"):
    return PostingRecord(
        company=company_obj,
        external_id=external_id,
        title="Engineer",
        url="https://example.com/1",
        first_seen_at=NOW,
        last_seen_at=NOW,
    )


def test_company_source_token_unique(session):
    session.add_all([company(), company()])
    with pytest.raises(IntegrityError):
        session.flush()


def test_posting_unique_per_company(session):
    a, b = company("a"), company("b")
    session.add_all([posting(a, "1"), posting(b, "1")])
    session.flush()  # same external_id under two companies is fine
    session.add(posting(a, "1"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_snapshot_unique_per_run_and_company(session):
    c = company()
    run = ScrapeRun(started_at=NOW, status="running")
    for minute in (0, 5):  # different times: only (run, company) may make them clash
        session.add(
            Snapshot(
                run=run,
                company=c,
                fetched_at=NOW.replace(minute=minute),
                status="ok",
                posting_count=0,
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


def test_foreign_keys_enforced(session):
    run = ScrapeRun(started_at=NOW, status="running")
    session.add(run)
    session.flush()
    session.add(
        Snapshot(run_id=run.id, company_id=999, fetched_at=NOW, status="ok", posting_count=0)
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_status_vocabularies_are_exact():
    assert RUN_STATUSES == ("running", "succeeded", "partial", "failed")
    assert SNAPSHOT_STATUSES == ("ok", "partial", "failed")


@pytest.mark.parametrize("status", RUN_STATUSES)
def test_run_status_accepts_known_values(session, status):
    session.add(ScrapeRun(started_at=NOW, status=status))
    session.flush()


def test_run_status_check_constraint(session):
    session.add(ScrapeRun(started_at=NOW, status="done"))
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("status", [*SNAPSHOT_STATUSES, "broken"])
def test_snapshot_status_check_constraint(session, status):
    run = ScrapeRun(started_at=NOW, status="running")
    session.add(
        Snapshot(run=run, company=company(), fetched_at=NOW, status=status, posting_count=0)
    )
    if status in SNAPSHOT_STATUSES:
        session.flush()
    else:
        with pytest.raises(IntegrityError):
            session.flush()


def test_snapshot_links_postings(session):
    c = company()
    run = ScrapeRun(started_at=NOW, status="running")
    p = posting(c)
    snap = Snapshot(run=run, company=c, fetched_at=NOW, status="ok", posting_count=1)
    snap.postings.append(p)
    session.add(snap)
    session.flush()
    session.expire_all()
    assert [x.external_id for x in session.get(Snapshot, snap.id).postings] == ["1"]


def test_column_lengths_come_from_model_limits():
    from jobsignal.models import DEPARTMENT_MAX, EXTERNAL_ID_MAX, TITLE_MAX

    columns = PostingRecord.__table__.c
    assert columns.title.type.length == TITLE_MAX
    assert columns.department.type.length == DEPARTMENT_MAX
    assert columns.external_id.type.length == EXTERNAL_ID_MAX


def test_failed_snapshot_may_have_null_posting_count(session):
    run = ScrapeRun(started_at=NOW, status="running")
    session.add(Snapshot(run=run, company=company(), fetched_at=NOW, status="failed"))
    session.flush()
