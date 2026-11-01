"""The demo 'time machine': backup first, then synthetic history the real pipeline flags red."""

import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from jobsignal import detect, harmonize, seed_demo
from jobsignal.models import Posting
from jobsignal.signals.trend import trends_for_scores
from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.repository import (
    finish_run,
    get_or_create_company,
    get_scores,
    record_snapshot,
    start_run,
)
from jobsignal.storage.schema import Company, PostingRecord, SignalScore

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)  # a Sunday, like the real "today"
REAL_SCRAPE = datetime(2026, 10, 31, 16, 55, tzinfo=UTC)
SPIKE_WEEK = date(2026, 10, 19)  # the last complete week before NOW
REAL_TABLE = [
    ("Software Engineer", "San Francisco, California"),
    ("Senior Account Executive", "London, United Kingdom"),
    ("Data Engineer", "Amsterdam, Netherlands"),
    ("Machine Learning Engineer", "Mountain View, California"),
]


def _real(token, n, at):
    return [
        Posting(
            source="greenhouse", company=token, external_id=f"{token}-{i}",
            title=REAL_TABLE[i % 4][0], location_raw=REAL_TABLE[i % 4][1],
            department=None, url=f"https://boards.greenhouse.io/{token}/jobs/{i}",
            first_published=at - timedelta(days=30), updated_at=None, fetched_at=at,
        )
        for i in range(n)
    ]  # fmt: skip


@pytest.fixture
def real_db(migrated_url, tmp_path):
    """A database as the real scraper leaves it: ONE scrape, the day before 'now'."""
    engine = make_engine(migrated_url)
    with make_session_factory(engine)() as session:
        for token, n in (("databricks", 40), ("stripe", 6)):
            company = get_or_create_company(session, "greenhouse", token, REAL_SCRAPE)
            run = start_run(session, REAL_SCRAPE)
            record_snapshot(session, run, company, _real(token, n, REAL_SCRAPE), REAL_SCRAPE)
            finish_run(session, run, REAL_SCRAPE)
        session.commit()
    engine.dispose()
    path = migrated_url.removeprefix("sqlite:///")
    return migrated_url, path


def counts(path) -> dict[str, int]:
    with sqlite3.connect(path) as db:
        return {
            table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            for table in ("companies", "snapshots", "postings", "snapshot_postings")
        }


def seed(path, backup, *extra) -> int:
    return seed_demo.main(["--db", str(path), "--backup", str(backup), "--now", NOW.isoformat(),
                           *extra])  # fmt: skip


def run_pipeline(url) -> None:
    assert harmonize.main(["--db", url]) == 0
    assert detect.main(["--db", url], now=lambda: NOW) == 0


def red_scores(url):
    engine = make_engine(url)
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(SignalScore, Company.board_token)
            .join(Company, Company.id == SignalScore.company_id)
            .where(SignalScore.detector == "volume", SignalScore.is_signal.is_(True))
        ).all()
        found = [
            (s.level, s.role_family, s.country_code, s.week_start, s.direction, s.z, s.id)
            for s, token in rows
            if token == "databricks"
        ]
    engine.dispose()
    return found


def test_backup_is_written_first_and_is_the_untouched_database(real_db, tmp_path, capsys):
    _url, path = real_db
    before = counts(path)
    backup = tmp_path / "jobsignal_real_backup.db"
    assert seed(path, backup) == 0
    assert counts(backup) == before  # the backup is the pre-seed database
    assert counts(path)["postings"] > before["postings"]
    out = capsys.readouterr().out
    assert str(backup) in out
    assert "--restore" in out  # tells the user how to undo it


def test_pipeline_flags_a_red_london_expansion_for_databricks(real_db, tmp_path):
    url, path = real_db
    assert seed(path, tmp_path / "backup.db") == 0
    run_pipeline(url)
    signals = red_scores(url)
    london = [s for s in signals if s[2] == "GB" and s[3] == SPIKE_WEEK]
    assert london, signals
    assert all(direction == "expansion" for *_, direction, _z, _id in london)
    company_gb = next(s for s in london if s[0] == "company_country")
    assert company_gb[5] > 5  # red band: |z| > 5
    assert any(s[0] == "company_family_country" and s[1] == "software_engineering"
               and s[5] > 5 for s in london)  # fmt: skip


def test_red_alert_has_an_eight_week_sparkline(real_db, tmp_path):
    url, path = real_db
    assert seed(path, tmp_path / "backup.db") == 0
    run_pipeline(url)
    score_id = next(s[6] for s in red_scores(url) if s[0] == "company_country" and s[2] == "GB")
    engine = make_engine(url)
    with make_session_factory(engine)() as session:
        ((score, token, run),) = get_scores(session, [score_id])
        stored_z = score.z
        points = trends_for_scores(session, [(score, token, run)])[score_id]
    engine.dispose()
    assert len(points) == 8
    assert all(p.value is not None for p in points)  # every week covered: a full sparkline
    assert points[-1].z == pytest.approx(stored_z)
    assert max(p.value for p in points[:-1]) <= 2  # a quiet London baseline before the spike


def test_real_postings_are_kept_open_and_unchanged(real_db, tmp_path):
    url, path = real_db
    assert seed(path, tmp_path / "backup.db") == 0
    engine = make_engine(url)
    with make_session_factory(engine)() as session:
        real = session.scalars(
            select(PostingRecord).where(PostingRecord.external_id.like("databricks-%"))
        ).all()
        assert len(real) == 40
        assert all(p.closed_at is None for p in real)
        assert {p.title for p in real} == {t for t, _ in REAL_TABLE}
    engine.dispose()


def test_refuses_to_overwrite_an_existing_backup(real_db, tmp_path):
    _url, path = real_db
    backup = tmp_path / "backup.db"
    backup.write_bytes(b"precious")
    before = counts(path)
    assert seed(path, backup) == 2
    assert backup.read_bytes() == b"precious"
    assert counts(path) == before


def test_refuses_to_seed_twice(real_db, tmp_path):
    _url, path = real_db
    assert seed(path, tmp_path / "first.db") == 0
    after = counts(path)
    assert seed(path, tmp_path / "second.db") == 2  # already contains synthetic history
    assert counts(path) == after


def test_restore_puts_the_real_database_back(real_db, tmp_path):
    _url, path = real_db
    before = counts(path)
    backup = tmp_path / "backup.db"
    assert seed(path, backup) == 0
    assert seed_demo.main(["--db", str(path), "--backup", str(backup), "--restore"]) == 0
    assert counts(path) == before
    assert backup.exists()  # kept until the user deletes it


def test_restore_without_backup_fails(real_db, tmp_path):
    _url, path = real_db
    assert seed_demo.main(["--db", str(path), "--backup", str(tmp_path / "x.db"), "--restore"]) == 2


def test_real_initial_load_is_not_counted_as_new_openings(real_db, tmp_path):
    """The real scrape must read as a continuation, not 40 'new' postings (or a re-import)."""
    from jobsignal.storage.repository import ok_snapshot_stats

    url, path = real_db
    assert seed(path, tmp_path / "backup.db") == 0
    engine = make_engine(url)
    with make_session_factory(engine)() as session:
        stats = ok_snapshot_stats(session)["databricks"]
    engine.dispose()
    real = next(s for s in stats if s[0] == REAL_SCRAPE)
    assert real[2] == 0  # new_count at the real snapshot
    first = min(stats)
    assert first[2] == first[1]  # only the very first (never-scored) snapshot is an initial load
