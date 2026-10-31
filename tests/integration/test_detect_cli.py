"""The detect command end-to-end on a migrated SQLite file with synthetic weekly scrapes."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from jobsignal.detect import main
from jobsignal.harmonization.locations import parse_locations
from jobsignal.harmonization.roles import classify_title
from jobsignal.models import Posting
from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.repository import (
    finish_run,
    get_or_create_company,
    record_snapshot,
    save_harmonization,
    start_run,
)
from jobsignal.storage.schema import PostingRecord, SignalRun, SignalScore
from jobsignal.weeks import week_start

pytestmark = pytest.mark.integration

WEEK0 = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)  # Tuesday; ISO week of Mon 2026-08-03


def posting(n, at):
    return Posting(
        source="greenhouse",
        company="acme",
        external_id=str(n),
        title="Account Executive",
        location_raw="San Francisco, CA",
        department="Sales",
        url=f"https://x.io/{n}",
        first_published=None,
        updated_at=None,
        fetched_at=at,
    )


def seed(db_url, new_per_week, outage_weeks=()):
    """Week 0 = initial load (2 pre-existing postings); week k adds new_per_week[k-1] openings.

    Weeks in ``outage_weeks`` record no snapshot: their openings are first seen a week later.
    """
    engine = make_engine(db_url)
    with make_session_factory(engine)() as session:
        company = get_or_create_company(session, "greenhouse", "acme", WEEK0)
        open_ids, next_id = [1, 2], 3
        for week, new in enumerate([0, *new_per_week]):
            at = WEEK0 + timedelta(weeks=week)
            open_ids += list(range(next_id, next_id + new))
            next_id += new
            if week in outage_weeks:
                continue
            run = start_run(session, at)
            record_snapshot(session, run, company, [posting(i, at) for i in open_ids], at)
            finish_run(session, run, at)
            session.commit()
        # a real schedule keeps scraping: one more snapshot after the last scored week
        at = WEEK0 + timedelta(weeks=len(new_per_week) + 1)
        run = start_run(session, at)
        record_snapshot(session, run, company, [posting(i, at) for i in open_ids], at)
        finish_run(session, run, at)
        session.commit()
        for row in session.scalars(select(PostingRecord)):
            roles, places = (
                classify_title(row.title, row.department),
                parse_locations(row.location_raw),
            )
            save_harmonization(session, row, roles, places, "t", WEEK0)
        session.commit()
    engine.dispose()
    return WEEK0 + timedelta(weeks=len(new_per_week) + 1, days=1)  # Wed after the last week


def query(db, statement):
    engine = make_engine(db)
    with make_session_factory(engine)() as session:
        result = session.execute(statement).all()
    engine.dispose()
    return result


def test_volume_spike_detected_end_to_end(migrated_url):
    now = seed(migrated_url, [2] * 9 + [9])  # baseline 2/week, spike of 9 in the last week

    assert main(["--db", migrated_url], now=lambda: now) == 0

    signals = query(
        migrated_url,
        select(SignalScore.level, SignalScore.role_family, SignalScore.country_code,
               SignalScore.z, SignalScore.direction, SignalScore.severity)
        .where(SignalScore.detector == "volume", SignalScore.is_signal.is_(True)),
    )  # fmt: skip
    cell = [s for s in signals if s.level == "company_family_country"]
    assert len(cell) == 1
    _level, family, country, z, direction, severity = cell[0]
    assert (family, country, direction, severity) == ("sales", "US", "expansion", "strong")
    assert z == pytest.approx(7 / 2**0.5)  # mu=2, s=0 -> sigma_eff = sqrt(2)


def test_freeze_detected_end_to_end(migrated_url):
    now = seed(migrated_url, [12] * 9 + [0])

    assert main(["--db", migrated_url], now=lambda: now) == 0

    rows = query(
        migrated_url,
        select(SignalScore.direction, SignalScore.z).where(
            SignalScore.detector == "volume",
            SignalScore.level == "company",
            SignalScore.is_signal.is_(True),
        ),
    )
    assert [(d, round(z, 3)) for d, z in rows] == [("contraction", round(-12 / 12**0.5, 3))]


def test_cold_start_reports_no_volume_signals(migrated_url, capsys):
    now = seed(migrated_url, [])  # a single (initial-load) snapshot

    assert main(["--db", migrated_url], now=lambda: now) == 0

    assert query(migrated_url, select(func.count()).select_from(SignalRun))[0][0] == 1
    volume_signals = query(
        migrated_url,
        select(func.count()).where(
            SignalScore.detector == "volume", SignalScore.is_signal.is_(True)
        ),
    )
    assert volume_signals[0][0] == 0
    assert "signals=0" in capsys.readouterr().err


def test_as_of_flag_controls_scored_week(migrated_url):
    now = seed(migrated_url, [2] * 9 + [9])
    spike_week = week_start(WEEK0 + timedelta(weeks=10))  # a Monday, like stored weeks
    early = (WEEK0 + timedelta(weeks=10)).strftime("%Y-%m-%d")  # spike week is not complete yet

    assert main(["--db", migrated_url, "--as-of", early], now=lambda: now) == 0

    weeks = {w for (w,) in query(migrated_url, select(SignalScore.week_start).where(
        SignalScore.detector == "volume"))}  # fmt: skip
    assert spike_week not in weeks


def test_bad_as_of_exits_2(migrated_url):
    with pytest.raises(SystemExit) as excinfo:
        main(["--db", migrated_url, "--as-of", "next tuesday"])
    assert excinfo.value.code == 2


def test_unmigrated_db_exits_2(tmp_path, capsys):
    empty = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    assert main(["--db", empty]) == 2
    assert "alembic upgrade head" in capsys.readouterr().err


def test_each_run_is_new(migrated_url):
    now = seed(migrated_url, [2] * 9 + [9])
    main(["--db", migrated_url], now=lambda: now)
    main(["--db", migrated_url], now=lambda: now)
    assert query(migrated_url, select(func.count()).select_from(SignalRun))[0][0] == 2


def company_volume_row(db):
    return query(
        db,
        select(SignalScore.status, SignalScore.baseline_weeks, SignalScore.baseline_mean).where(
            SignalScore.detector == "volume", SignalScore.level == "company"
        ),
    )


def test_outage_week_and_its_backlog_week_are_skipped_by_the_baseline(migrated_url):
    """5/week; no scrape in week 6, so its 5 openings surface in week 7 (10). The 14-day gap
    hides weeks 5, 6 and 7. The baseline for week 13 is the 8 covered weeks
    2,3,4,8,9,10,11,12 = 5.0 - neither the outage zero nor the backlog 10."""
    now = seed(migrated_url, [5] * 13, outage_weeks={6})
    assert main(["--db", migrated_url], now=lambda: now) == 0
    assert company_volume_row(migrated_url) == [("scored", 8, 5.0)]


def test_first_snapshot_week_is_not_a_baseline_week(migrated_url):
    """The initial-load week shows ~0 new openings by construction; counting it would drag
    young baselines down. Weeks 1..7 = 7 real baseline weeks -> insufficient history."""
    now = seed(migrated_url, [2] * 7 + [9])
    assert main(["--db", migrated_url], now=lambda: now) == 0
    assert company_volume_row(migrated_url) == [("insufficient_history", 7, 2.0)]
