from datetime import UTC, date, datetime, timedelta

import pytest

from jobsignal.harmonization.locations import parse_locations
from jobsignal.harmonization.roles import classify_title
from jobsignal.models import Posting
from jobsignal.signals.events import to_frame
from jobsignal.storage.repository import (
    finish_run,
    get_or_create_company,
    ok_snapshot_stats,
    opening_rows,
    record_failed_snapshot,
    record_snapshot,
    save_harmonization,
    start_run,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)  # Thursday; ISO week starts Mon 2026-09-28


def posting(
    external_id, at, location="San Francisco, CA", title="Software Engineer", published=None
):
    return Posting(source="greenhouse", company="acme", external_id=external_id, title=title,
                   location_raw=location, department=None, url=f"https://x.io/{external_id}",
                   first_published=published, updated_at=None, fetched_at=at)  # fmt: skip


def snapshot(session, company, postings, at, complete=True):
    run = start_run(session, at)
    record_snapshot(session, run, company, postings, at, complete=complete)
    finish_run(session, run, at)
    session.commit()


def harmonize_all(session):
    from jobsignal.storage.schema import PostingRecord

    for row in session.query(PostingRecord):
        save_harmonization(
            session, row, classify_title(row.title), parse_locations(row.location_raw), "t", T0
        )
    session.commit()


@pytest.fixture
def company(session):
    return get_or_create_company(session, "greenhouse", "acme", T0)


def test_first_snapshot_postings_are_not_new_openings(session, company):
    snapshot(session, company, [posting("a", T0), posting("b", T0)], T0)
    later = T0 + timedelta(days=9)
    snapshot(session, company, [posting(i, later) for i in "abc"], later)
    harmonize_all(session)

    frame = to_frame(opening_rows(session), basis="observed")

    assert frame["posting_id"].nunique() == 1
    assert frame["event_week"].tolist() == [date(2026, 10, 5)]  # Monday of T0 + 9 days


def test_multi_country_posting_one_row_per_country(session, company):
    snapshot(session, company, [posting("seed", T0)], T0)
    later = T0 + timedelta(days=7)
    batch = [
        posting("seed", later),
        posting("intl", later, "San Francisco, CA | London, UK"),
        posting("two-us", later, "San Francisco, CA | Seattle, WA"),
    ]
    snapshot(session, company, batch, later)
    harmonize_all(session)

    frame = to_frame(opening_rows(session), basis="observed")
    by_posting = frame.groupby("posting_id")["country"].apply(sorted).to_dict()
    assert sorted(by_posting.values()) == [["GB", "US"], ["US"]]


def test_unlocated_posting_uses_zz(session, company):
    snapshot(session, company, [posting("seed", T0)], T0)
    later = T0 + timedelta(days=7)
    snapshot(
        session, company, [posting("seed", later), posting("nowhere", later, location="N/A")], later
    )
    harmonize_all(session)

    frame = to_frame(opening_rows(session), basis="observed")
    assert frame["country"].tolist() == ["ZZ"]


def test_unharmonized_family_is_unclassified(session, company):
    snapshot(session, company, [posting("seed", T0)], T0)
    later = T0 + timedelta(days=7)
    snapshot(session, company, [posting("seed", later), posting("new", later)], later)

    frame = to_frame(opening_rows(session), basis="observed")
    assert frame["role_family"].tolist() == ["unclassified"]


def test_published_basis_uses_first_published_week(session, company):
    published = datetime(2026, 9, 20, 23, 30, tzinfo=UTC)  # Sunday → ISO week of Mon 2026-09-14
    snapshot(session, company, [posting("a", T0, published=published), posting("b", T0)], T0)
    harmonize_all(session)

    frame = to_frame(opening_rows(session), basis="published")
    assert frame["posting_id"].nunique() == 1  # 'b' has no first_published
    assert frame["event_week"].tolist() == [date(2026, 9, 14)]


def test_ok_snapshot_stats_counts_new_postings_and_skips_non_ok(session, company):
    snapshot(session, company, [posting("a", T0), posting("b", T0)], T0)  # initial load
    failed_at = T0 + timedelta(days=7)
    run = start_run(session, failed_at)
    record_failed_snapshot(session, run, company, "RetryExhaustedError", failed_at)
    session.commit()
    partial_at = T0 + timedelta(days=8)
    snapshot(session, company, [posting("a", partial_at), posting("c", partial_at)], partial_at,
             complete=False)  # fmt: skip
    ok_at = T0 + timedelta(days=9)
    snapshot(session, company, [posting(i, ok_at) for i in "abcd"], ok_at)

    assert ok_snapshot_stats(session) == {"acme": [(T0, 2, 2), (ok_at, 4, 1)]}
