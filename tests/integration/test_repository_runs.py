from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from jobsignal.storage.repository import finish_run, get_or_create_company, start_run
from jobsignal.storage.schema import Company, ScrapeRun, Snapshot

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 1, 9, 5, tzinfo=UTC)


def test_get_or_create_company_is_idempotent(session):
    first = get_or_create_company(session, "greenhouse", "anthropic", T0)
    session.commit()
    second = get_or_create_company(session, "greenhouse", "anthropic", T1)

    assert second.id == first.id
    assert second.created_at == T0
    assert session.scalar(select(func.count()).select_from(Company)) == 1


def test_same_token_on_different_sources_is_a_different_company(session):
    gh = get_or_create_company(session, "greenhouse", "acme", T0)
    ashby = get_or_create_company(session, "ashby", "acme", T0)
    session.flush()
    assert gh.id != ashby.id


def test_start_run_is_running(session):
    run = start_run(session, T0)
    session.commit()
    assert (run.status, run.started_at, run.finished_at) == ("running", T0, None)
    assert session.get(ScrapeRun, run.id) is run


@pytest.mark.parametrize(
    ("snapshot_statuses", "expected"),
    [
        (["ok", "ok"], "succeeded"),
        (["ok", "failed"], "partial"),
        (["failed", "failed"], "failed"),
        (["partial"], "partial"),
        (["ok", "partial"], "partial"),
        ([], "failed"),
    ],
)
def test_finish_run_status_matrix(session, snapshot_statuses, expected):
    run = start_run(session, T0)
    for i, status in enumerate(snapshot_statuses):
        company = get_or_create_company(session, "greenhouse", f"c{i}", T0)
        session.add(
            Snapshot(run=run, company=company, fetched_at=T0, status=status, posting_count=0)
        )
    session.flush()

    finish_run(session, run, T1)
    session.commit()

    assert run.status == expected
    assert run.finished_at == T1


def test_finish_run_only_counts_its_own_snapshots(session):
    company = get_or_create_company(session, "greenhouse", "anthropic", T0)
    earlier = start_run(session, T0)
    session.add(Snapshot(run=earlier, company=company, fetched_at=T0, status="ok", posting_count=0))
    current = start_run(session, T1)
    session.flush()

    assert finish_run(session, current, T1).status == "failed"
