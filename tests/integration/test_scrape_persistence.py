"""The scrape CLI persists runs, snapshots and postings to the database."""

import copy
import json

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from jobsignal.scrape import main
from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.schema import (
    Company,
    PostingRecord,
    ScrapeRun,
    Snapshot,
    snapshot_postings,
)
from tests.conftest import PROJECT_ROOT
from tests.integration.test_run_scrape import board_transport

pytestmark = pytest.mark.integration


def run(args, db, requested=None):
    return main(
        [*args, "--db", db],
        transport=board_transport([] if requested is None else requested),
        min_interval=0,
    )


def query(db, statement):
    engine = make_engine(db)
    with make_session_factory(engine)() as session:
        result = session.execute(statement).all()
    engine.dispose()
    return result


def count(db, table):
    return query(db, select(func.count()).select_from(table))[0][0]


def test_run_persists_snapshot_and_postings(migrated_url):
    assert run(["anthropic"], migrated_url) == 0

    assert query(migrated_url, select(ScrapeRun.status)) == [("succeeded",)]
    assert query(migrated_url, select(Snapshot.status, Snapshot.posting_count)) == [("ok", 6)]
    open_rows = query(
        migrated_url, select(PostingRecord.id).where(PostingRecord.closed_at.is_(None))
    )
    assert len(open_rows) == 6


def test_second_identical_run_adds_snapshot_not_postings(migrated_url):
    run(["anthropic"], migrated_url)
    run(["anthropic"], migrated_url)

    assert count(migrated_url, PostingRecord) == 6
    assert count(migrated_url, Snapshot) == 2
    assert count(migrated_url, snapshot_postings) == 12


def test_failed_company_recorded_and_run_partial(migrated_url):
    assert run(["nosuchboard", "anthropic"], migrated_url) == 1

    assert query(migrated_url, select(ScrapeRun.status)) == [("partial",)]
    failed = query(migrated_url, select(Snapshot.error_type).where(Snapshot.status == "failed"))
    assert failed == [("SourceNotFoundError",)]


def test_invalid_token_recorded_as_failed_without_company_row_pollution(migrated_url):
    assert run(["../evil"], migrated_url) == 1
    assert query(migrated_url, select(ScrapeRun.status)) == [("failed",)]
    assert count(migrated_url, Company) == 0
    assert count(migrated_url, Snapshot) == 0


def test_duplicate_company_args_scraped_once(migrated_url):
    requested = []
    assert run(["anthropic", "anthropic"], migrated_url, requested) == 0

    assert requested == ["/v1/boards/anthropic/departments"]
    assert count(migrated_url, Snapshot) == 1


def test_unmigrated_database_exits_2_with_hint(tmp_path, capsys):
    requested = []
    empty = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"

    assert run(["anthropic"], empty, requested) == 2

    assert "alembic upgrade head" in capsys.readouterr().err
    assert requested == []


def test_db_flag_overrides_settings(migrated_url, tmp_path, monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_DATABASE_URL", f"sqlite:///{(tmp_path / 'other.db').as_posix()}")
    assert run(["anthropic"], migrated_url) == 0
    assert count(migrated_url, Snapshot) == 1


FIXTURE = json.loads(
    (PROJECT_ROOT / "tests/fixtures/greenhouse/departments_anthropic.json").read_text(
        encoding="utf-8"
    )
)


def payload_transport(payload):
    return httpx.MockTransport(lambda request: httpx.Response(200, json=payload))


def test_incomplete_payload_never_closes_postings(migrated_url):
    assert (
        main(
            ["anthropic", "--db", migrated_url],
            transport=payload_transport(FIXTURE),
            min_interval=0,
        )
        == 0
    )
    broken = copy.deepcopy(FIXTURE)
    broken["departments"][0]["jobs"] = None  # upstream glitch drops a department

    code = main(
        ["anthropic", "--db", migrated_url], transport=payload_transport(broken), min_interval=0
    )

    assert code == 1
    open_rows = query(
        migrated_url, select(PostingRecord.id).where(PostingRecord.closed_at.is_(None))
    )
    assert len(open_rows) == 6
    statuses = query(migrated_url, select(Snapshot.status).order_by(Snapshot.id))
    assert statuses == [("ok",), ("partial",)]
    assert query(migrated_url, select(ScrapeRun.status).order_by(ScrapeRun.id))[-1] == ("partial",)


def _no_running_runs(db):
    return query(db, select(ScrapeRun.status).where(ScrapeRun.status == "running")) == []


def test_database_error_mid_run_is_recorded_not_a_zombie(migrated_url, monkeypatch):
    import jobsignal.scrape as scrape

    real = scrape.record_snapshot
    calls = {"n": 0}

    def flaky(session, run, company, postings, fetched_at, complete=True):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OperationalError("INSERT ...", {}, Exception("database is locked"))
        return real(session, run, company, postings, fetched_at, complete=complete)

    monkeypatch.setattr(scrape, "record_snapshot", flaky)
    code = main(
        ["anthropic", "stripe", "--db", migrated_url],
        transport=payload_transport(FIXTURE),
        min_interval=0,
    )

    assert code == 1
    assert _no_running_runs(migrated_url)
    assert query(migrated_url, select(ScrapeRun.status)) == [("partial",)]
    assert query(migrated_url, select(Snapshot.error_type).where(Snapshot.status == "failed")) == [
        ("OperationalError",)
    ]


def test_interrupt_mid_run_still_finishes_the_run(migrated_url, monkeypatch):
    import jobsignal.scrape as scrape

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(scrape, "record_snapshot", interrupted)
    with pytest.raises(KeyboardInterrupt):
        main(
            ["anthropic", "--db", migrated_url],
            transport=payload_transport(FIXTURE),
            min_interval=0,
        )

    assert _no_running_runs(migrated_url)
    assert query(migrated_url, select(ScrapeRun.status)) == [("failed",)]
