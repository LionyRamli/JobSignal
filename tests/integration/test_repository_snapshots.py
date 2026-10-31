from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from jobsignal.models import Posting
from jobsignal.storage.repository import (
    StaleSnapshotError,
    get_or_create_company,
    open_postings,
    record_failed_snapshot,
    record_snapshot,
    start_run,
)
from jobsignal.storage.schema import PostingRecord, snapshot_postings

pytestmark = pytest.mark.integration

T1 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
T3 = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def posting(external_id, company="anthropic", fetched_at=T1, **overrides):
    fields = {
        "source": "greenhouse",
        "company": company,
        "external_id": external_id,
        "title": f"Engineer {external_id}",
        "location_raw": "San Francisco, CA",
        "department": "Research",
        "url": f"https://job-boards.greenhouse.io/{company}/jobs/{external_id}",
        "first_published": None,
        "updated_at": None,
        "fetched_at": fetched_at,
    }
    fields.update(overrides)
    return Posting(**fields)


@pytest.fixture
def company(session):
    return get_or_create_company(session, "greenhouse", "anthropic", T1)


def snap(session, company, ids, at, **overrides):
    run = start_run(session, at)
    result = record_snapshot(
        session, run, company, [posting(i, fetched_at=at, **overrides) for i in ids], at
    )
    session.commit()
    return result


def record(session, company, external_id):
    return session.scalar(
        select(PostingRecord).where(
            PostingRecord.company_id == company.id, PostingRecord.external_id == external_id
        )
    )


def membership_count(session):
    return session.scalar(select(func.count()).select_from(snapshot_postings))


def test_first_snapshot_inserts_postings_and_links_them(session, company):
    snapshot = snap(session, company, ["a", "b", "c"], T1)

    rows = session.scalars(select(PostingRecord)).all()
    assert len(rows) == 3
    assert all((r.first_seen_at, r.last_seen_at, r.closed_at) == (T1, T1, None) for r in rows)
    assert membership_count(session) == 3
    assert (snapshot.status, snapshot.posting_count, snapshot.fetched_at) == ("ok", 3, T1)


def test_second_snapshot_updates_last_seen_and_fields(session, company):
    snap(session, company, ["a"], T1)
    snap(session, company, ["a"], T2, title="Staff Engineer", department="Applied AI")

    row = record(session, company, "a")
    assert session.scalar(select(func.count()).select_from(PostingRecord)) == 1
    assert (row.title, row.department) == ("Staff Engineer", "Applied AI")
    assert (row.first_seen_at, row.last_seen_at, row.closed_at) == (T1, T2, None)
    assert membership_count(session) == 2


def test_missing_posting_is_closed_at_snapshot_time(session, company):
    snap(session, company, ["a", "b"], T1)
    snap(session, company, ["a"], T2)

    assert record(session, company, "b").closed_at == T2
    assert record(session, company, "b").last_seen_at == T1
    assert [p.external_id for p in open_postings(session, company)] == ["a"]


def test_already_closed_posting_keeps_original_close_time(session, company):
    snap(session, company, ["a", "b"], T1)
    snap(session, company, ["a"], T2)
    snap(session, company, ["a"], T3)

    assert record(session, company, "b").closed_at == T2


def test_reopened_posting_clears_closed_at_keeps_first_seen(session, company):
    snap(session, company, ["a"], T1)
    snap(session, company, [], T2)
    snap(session, company, ["a"], T3)

    row = record(session, company, "a")
    assert (row.first_seen_at, row.last_seen_at, row.closed_at) == (T1, T3, None)


def test_failed_snapshot_closes_nothing(session, company):
    snap(session, company, ["a", "b"], T1)
    run = start_run(session, T2)
    failed = record_failed_snapshot(session, run, company, "RetryExhaustedError", T2)
    session.commit()

    assert [p.external_id for p in open_postings(session, company)] == ["a", "b"]
    assert all(record(session, company, i).last_seen_at == T1 for i in ["a", "b"])
    assert (failed.status, failed.posting_count, failed.error_type) == (
        "failed",
        None,  # not 0: a failed fetch must not read as "zero openings"
        "RetryExhaustedError",
    )
    assert membership_count(session) == 2


def test_empty_successful_snapshot_closes_all(session, company):
    snap(session, company, ["a"], T1)
    snapshot = snap(session, company, [], T2)

    assert record(session, company, "a").closed_at == T2
    assert snapshot.posting_count == 0


def test_other_companies_untouched(session, company):
    other = get_or_create_company(session, "greenhouse", "stripe", T1)
    run = start_run(session, T1)
    record_snapshot(session, run, other, [posting("x", company="stripe")], T1)
    session.commit()

    snap(session, company, ["a"], T1)
    snap(session, company, [], T2)

    assert record(session, other, "x").closed_at is None


def test_duplicate_external_ids_in_one_fetch_counted_once(session, company):
    run = start_run(session, T1)
    snapshot = record_snapshot(session, run, company, [posting("a"), posting("a")], T1)
    session.commit()

    assert snapshot.posting_count == 1
    assert membership_count(session) == 1


@pytest.mark.parametrize(
    "foreign",
    [{"company": "stripe"}, {"source": "lever"}],
)
def test_posting_from_other_company_rejected(session, company, foreign):
    run = start_run(session, T1)
    session.commit()
    with pytest.raises(ValueError, match="does not belong"):
        record_snapshot(session, run, company, [posting("a"), posting("b", **foreign)], T1)
    session.rollback()

    assert session.scalar(select(func.count()).select_from(PostingRecord)) == 0


def test_large_snapshot_round_trip(session, company):
    ids = [str(i) for i in range(2500)]  # bigger than SQLite's default variable limit
    snap(session, company, ids, T1)
    snap(session, company, ids[:2000], T2)

    assert len(open_postings(session, company)) == 2000
    assert membership_count(session) == 4500


def test_incomplete_snapshot_upserts_seen_but_closes_nothing(session, company):
    snap(session, company, ["a", "b"], T1)
    run = start_run(session, T2)
    snapshot = record_snapshot(
        session, run, company, [posting("a", fetched_at=T2)], T2, complete=False
    )
    session.commit()

    assert (snapshot.status, snapshot.posting_count) == ("partial", 1)
    assert [p.external_id for p in open_postings(session, company)] == ["a", "b"]
    assert record(session, company, "a").last_seen_at == T2
    assert record(session, company, "b").last_seen_at == T1


def test_out_of_order_snapshot_is_rejected_and_changes_nothing(session, company):
    snap(session, company, ["a", "b"], T2)
    run = start_run(session, T1)
    with pytest.raises(StaleSnapshotError):
        record_snapshot(session, run, company, [posting("a", fetched_at=T1)], T1)
    session.rollback()

    row_a, row_b = record(session, company, "a"), record(session, company, "b")
    assert (row_a.last_seen_at, row_b.closed_at) == (T2, None)
