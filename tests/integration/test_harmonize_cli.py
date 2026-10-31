"""The harmonize command over a real migrated SQLite file seeded through the scrape path."""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select

import jobsignal.harmonization.taxonomy as taxonomy
from jobsignal.extraction.greenhouse import GreenhouseSource
from jobsignal.extraction.http_client import HttpClient
from jobsignal.extraction.rate_limit import RateLimiter
from jobsignal.harmonize import main
from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.repository import get_or_create_company, record_snapshot, start_run
from jobsignal.storage.schema import Location, PostingRecord, posting_locations
from tests.conftest import PROJECT_ROOT

pytestmark = pytest.mark.integration

FIXTURE = (PROJECT_ROOT / "tests/fixtures/greenhouse/departments_anthropic.json").read_bytes()
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def seeded(migrated_url):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=FIXTURE))
    with HttpClient(transport=transport, rate_limiter=RateLimiter(0)) as http:
        postings = GreenhouseSource(http, clock=lambda: T0).fetch_postings("anthropic")
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as session:
        company = get_or_create_company(session, "greenhouse", "anthropic", T0)
        record_snapshot(session, start_run(session, T0), company, postings, T0)
        session.commit()
    engine.dispose()
    return migrated_url


def query(db, statement):
    engine = make_engine(db)
    with make_session_factory(engine)() as session:
        result = session.execute(statement).all()
    engine.dispose()
    return result


def test_harmonizes_all_pending(seeded):
    assert main(["--db", seeded]) == 0

    rows = query(
        seeded,
        select(
            PostingRecord.title,
            PostingRecord.role_family,
            PostingRecord.seniority,
            PostingRecord.taxonomy_version,
        ),
    )
    assert len(rows) == 6
    assert all(version == taxonomy.TAXONOMY_VERSION for *_, version in rows)
    by_title = {title: (family, seniority) for title, family, seniority, _ in rows}
    assert by_title["Staff+ Research Scientist, Multi-Agent"] == ("ml_research", "staff_plus")
    assert by_title["Executive Communications Writer"] == ("marketing", "mid")
    # "San Francisco, CA | New York City, NY" etc. -> shared canonical locations
    keys = {k for (k,) in query(seeded, select(Location.key))}
    assert {"city|US|US-CA|San Francisco", "city|US|US-NY|New York City"} <= keys
    assert query(seeded, select(func.count()).select_from(posting_locations))[0][0] >= 6


def test_rerun_same_version_is_noop(seeded, capsys):
    main(["--db", seeded])
    first = query(
        seeded, select(PostingRecord.id, PostingRecord.harmonized_at).order_by(PostingRecord.id)
    )
    capsys.readouterr()
    assert main(["--db", seeded]) == 0

    second = query(
        seeded, select(PostingRecord.id, PostingRecord.harmonized_at).order_by(PostingRecord.id)
    )
    assert second == first
    assert "harmonized=0 " in capsys.readouterr().err


def test_version_bump_reprocesses(seeded, monkeypatch):
    main(["--db", seeded])
    monkeypatch.setattr(taxonomy, "TAXONOMY_VERSION", "2099.1.1")
    assert main(["--db", seeded]) == 0

    versions = {v for (v,) in query(seeded, select(PostingRecord.taxonomy_version))}
    assert versions == {"2099.1.1"}


def test_batches_commit_independently(seeded):
    assert main(["--db", seeded, "--batch-size", "2"]) == 0
    pending = query(
        seeded, select(PostingRecord.id).where(PostingRecord.taxonomy_version.is_(None))
    )
    assert pending == []


def test_summary_reports_unresolved(seeded, capsys):
    engine = make_engine(seeded)
    with make_session_factory(engine)() as session:
        row = session.scalars(select(PostingRecord).limit(1)).one()
        row.location_raw = "Atlantis; Seattle"
        session.commit()
    engine.dispose()

    main(["--db", seeded])
    summary = [line for line in capsys.readouterr().err.splitlines() if "harmonized=" in line]
    assert len(summary) == 1
    assert "harmonized=6 " in summary[0]
    assert "unresolved_pieces=1 " in summary[0]
    assert "Atlantis" in summary[0]


def test_unmigrated_db_exits_2(tmp_path, capsys):
    empty = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    assert main(["--db", empty]) == 2
    assert "alembic upgrade head" in capsys.readouterr().err
