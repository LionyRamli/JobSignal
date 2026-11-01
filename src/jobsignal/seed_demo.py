"""Demo 'time machine': synthetic hiring history so the volume detector has a baseline.

FOR DEMONSTRATIONS ONLY. The real scraper needs at least 8 continuously covered weeks before
`volume` can score anything. This script backs up the database, then writes ~10 weeks of
synthetic Greenhouse history for one company (default: databricks):

- daily `ok` snapshots (with scrape runs) from the first snapshot week up to now;
- a quiet baseline of 2-4 new AI/engineering postings per week, mostly outside the UK;
- in the last complete week, a hiring spike of 40 AI Infrastructure Engineer / Solutions
  Architect postings in London, GB.

The real postings of that company are kept and stay open; their first-seen time moves back to
the first synthetic snapshot so the history reads as one continuous series (otherwise the real
initial load would look like a burst of new openings). Synthetic postings are marked: their
external ids start with ``demo-`` and their URLs point at example.com.

    uv run python scripts/seed_historical_data.py            # backup, then seed
    uv run python scripts/seed_historical_data.py --restore  # put the real database back
"""

import argparse
import random
import sqlite3
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from jobsignal.storage.db import make_engine, make_session_factory
from jobsignal.storage.repository import get_or_create_company
from jobsignal.storage.schema import (
    Company,
    PostingRecord,
    ScrapeRun,
    Snapshot,
    snapshot_postings,
)
from jobsignal.weeks import week_start

EXIT_OK, EXIT_REFUSED = 0, 2
DEMO_PREFIX = "demo-"
SNAPSHOT_HOUR = time(9, 0, tzinfo=UTC)
HISTORY_WEEKS = 10  # first-snapshot week (never scored) + 8 baseline weeks + the spike week
SPIKE_SIZE = 40
CLOSE_SHARE = 0.35  # share of baseline postings filled (closed) before now

BASELINE_ROLES = [
    ("Software Engineer, Data Platform", "Engineering"),
    ("Senior Software Engineer - Spark Performance", "Engineering"),
    ("Machine Learning Engineer", "Engineering"),
    ("Staff Software Engineer, Serverless", "Engineering"),
    ("AI Engineer, Mosaic AI", "Engineering"),
    ("Senior Machine Learning Engineer, Model Serving", "Engineering"),
    ("Backend Software Engineer, Unity Catalog", "Engineering"),
    ("Solutions Architect", "Field Engineering"),
]
BASELINE_PLACES = [
    "San Francisco, California",
    "Mountain View, California",
    "Seattle, Washington",
    "Amsterdam, Netherlands",
    "Berlin, Germany",
    "Bengaluru, India",
]
SPIKE_ROLES = [
    ("AI Infrastructure Engineer", "Engineering"),
    ("Senior AI Infrastructure Engineer", "Engineering"),
    ("Staff AI Infrastructure Engineer - GPU Platform", "Engineering"),
    ("AI Infrastructure Engineer, Model Training", "Engineering"),
    ("Solutions Architect", "Field Engineering"),
    ("Senior Solutions Architect, Generative AI", "Field Engineering"),
]
LONDON = "London, United Kingdom"


def _restore(db: Path, backup: Path) -> int:
    if not backup.is_file():
        print(f"No backup found at {backup}: nothing to restore.", file=sys.stderr)
        return EXIT_REFUSED
    _copy_sqlite(backup, db)
    print(
        f"Restored {db} from {backup} (the backup is kept; delete it when you no longer need it)."
    )
    return EXIT_OK


def _copy_sqlite(source: Path, target: Path) -> None:
    """A consistent copy through SQLite's backup API (safe even with an open WAL)."""
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)


def _refusal(session: Session, token: str) -> str | None:
    company = session.scalar(select(Company).where(Company.board_token == token))
    if company is None:
        return None
    seeded = session.scalar(
        select(func.count())
        .select_from(PostingRecord)
        .where(PostingRecord.company_id == company.id)
        .where(PostingRecord.external_id.like(f"{DEMO_PREFIX}%"))
    )
    if seeded:
        return f"{token} already contains synthetic history: restore the backup first (--restore)."
    return None


def _snapshot_times(first_week: date, now: datetime) -> list[datetime]:
    times, day = [], first_week
    while (moment := datetime.combine(day, SNAPSHOT_HOUR)) < now:
        times.append(moment)
        day += timedelta(days=1)
    return times


def _plan_postings(rng: random.Random, times: list[datetime], spike_week: date) -> list[dict]:
    """Synthetic openings: (first seen, title, department, place, closes) per posting."""
    first_week = week_start(times[0])
    by_week: dict[date, list[datetime]] = {}
    for moment in times[1:]:  # nothing new at the very first snapshot (the initial load)
        if week_start(moment) != first_week:
            by_week.setdefault(week_start(moment), []).append(moment)
    planned = []
    for index, (week, days) in enumerate(sorted(by_week.items())):
        workdays = [d for d in days if d.weekday() < 5] or days
        for _ in range(rng.randint(2, 4)):  # quiet baseline: 2-4 AI/engineering roles a week
            title, department = rng.choice(BASELINE_ROLES)
            planned.append(
                {"seen": rng.choice(workdays), "title": title, "department": department,
                 "place": rng.choice(BASELINE_PLACES), "may_close": week != spike_week}
            )  # fmt: skip
        if week < spike_week and index % 2 == 0:  # an occasional London hire (~1 every 2 weeks)
            title, department = rng.choice(BASELINE_ROLES)
            planned.append(
                {"seen": rng.choice(workdays), "title": title, "department": department,
                 "place": LONDON, "may_close": True}
            )  # fmt: skip
        if week == spike_week:  # the European AI-infrastructure expansion
            for i in range(SPIKE_SIZE):
                title, department = SPIKE_ROLES[i % len(SPIKE_ROLES)]
                planned.append(
                    {"seen": workdays[i % len(workdays)], "title": title,
                     "department": department, "place": LONDON, "may_close": False}
                )  # fmt: skip
    return planned


def _seed(session: Session, token: str, now: datetime, rng: random.Random) -> dict:
    current_week = week_start(now)
    spike_week = current_week - timedelta(weeks=1)  # the last complete week: what detect scores
    first_week = spike_week - timedelta(weeks=HISTORY_WEEKS - 1)
    times = _snapshot_times(first_week, now)
    start = times[0]

    company = get_or_create_company(session, "greenhouse", token, start)
    company.created_at = min(company.created_at, start)

    # the real initial load becomes "already open when synthetic scraping began"
    real_first = session.scalar(
        select(func.min(Snapshot.fetched_at)).where(Snapshot.company_id == company.id)
    )
    if real_first is not None:
        for posting in session.scalars(
            select(PostingRecord).where(
                PostingRecord.company_id == company.id, PostingRecord.first_seen_at == real_first
            )
        ):
            posting.first_seen_at = min(posting.first_seen_at, start)

    synthetic = []
    for n, plan in enumerate(_plan_postings(rng, times, spike_week), start=1):
        seen = plan["seen"]
        closed = None
        if plan["may_close"] and rng.random() < CLOSE_SHARE:
            later = [t for t in times if t >= seen + timedelta(days=rng.randint(21, 42))]
            closed = later[0] if later else None
        posting = PostingRecord(
            company_id=company.id,
            external_id=f"{DEMO_PREFIX}{n}",
            title=plan["title"],
            location_raw=plan["place"],
            department=plan["department"],
            url=f"https://example.com/jobsignal-demo/{token}/{n}",
            first_published=seen - timedelta(hours=rng.randint(0, 36)),
            updated_at=None,
            first_seen_at=seen,
            last_seen_at=seen,
            closed_at=closed,
        )
        session.add(posting)
        synthetic.append(posting)
    session.flush()

    postings = session.scalars(
        select(PostingRecord).where(PostingRecord.company_id == company.id)
    ).all()

    def open_at(moment: datetime) -> list[PostingRecord]:
        return [
            p for p in postings
            if p.first_seen_at <= moment and (p.closed_at is None or p.closed_at > moment)
        ]  # fmt: skip

    links = []
    for moment in times:
        run = ScrapeRun(started_at=moment, finished_at=moment + timedelta(seconds=30),
                        status="succeeded")  # fmt: skip
        listed = open_at(moment)
        snapshot = Snapshot(run=run, company_id=company.id, fetched_at=moment, status="ok",
                            posting_count=len(listed))  # fmt: skip
        session.add_all([run, snapshot])
        session.flush()
        links += [{"snapshot_id": snapshot.id, "posting_id": p.id} for p in listed]
        for p in listed:
            p.last_seen_at = max(p.last_seen_at, moment)

    # real complete fetches must list the synthetic postings that were open at that time too
    synthetic_ids = {p.id for p in synthetic}
    for snapshot in session.scalars(
        select(Snapshot).where(
            Snapshot.company_id == company.id, Snapshot.status == "ok",
            Snapshot.fetched_at.not_in(times),
        )
    ):  # fmt: skip
        extra = [p for p in open_at(snapshot.fetched_at) if p.id in synthetic_ids]
        links += [{"snapshot_id": snapshot.id, "posting_id": p.id} for p in extra]
        snapshot.posting_count = (snapshot.posting_count or 0) + len(extra)
        for p in extra:
            p.last_seen_at = max(p.last_seen_at, snapshot.fetched_at)
    if links:
        session.execute(insert(snapshot_postings), links)
    return {
        "snapshots": len(times),
        "synthetic_postings": len(synthetic),
        "spike_week": spike_week,
        "first_snapshot": start,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DEMO ONLY: back up the database, then add synthetic hiring history."
    )
    parser.add_argument("--db", type=Path, default=Path("jobsignal.db"), help="SQLite file")
    parser.add_argument("--backup", type=Path, default=Path("jobsignal_real_backup.db"))
    parser.add_argument("--company", default="databricks", help="board token to seed")
    parser.add_argument("--seed", type=int, default=42, help="random seed (reproducible data)")
    parser.add_argument("--now", type=datetime.fromisoformat, default=None,
                        help="pretend 'now' (ISO-8601, UTC); default: the real clock")  # fmt: skip
    parser.add_argument("--restore", action="store_true",
                        help="copy the backup over the database and stop")  # fmt: skip
    args = parser.parse_args(argv)

    if args.restore:
        return _restore(args.db, args.backup)
    if not args.db.is_file():
        print(f"No database at {args.db}: run `uv run alembic upgrade head` first.",
              file=sys.stderr)  # fmt: skip
        return EXIT_REFUSED
    if args.backup.exists():
        print(
            f"Refusing to run: {args.backup} already exists and may hold your REAL data.\n"
            f"Restore it first (--restore) or move it somewhere safe.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    now = (args.now or datetime.now(UTC)).astimezone(UTC)

    engine = make_engine(f"sqlite:///{args.db.as_posix()}")
    try:
        with make_session_factory(engine)() as session:
            if reason := _refusal(session, args.company):
                print(f"Refusing to run: {reason}", file=sys.stderr)
                return EXIT_REFUSED
        engine.dispose()  # release the file before copying it

        _copy_sqlite(args.db, args.backup)  # CRITICAL SAFEGUARD: before any change
        print(f"Backed up the real database: {args.db} -> {args.backup}")
        print("  To restore it after the demo:")
        print(f"    uv run python scripts/seed_historical_data.py --restore "
              f"--db {args.db} --backup {args.backup}")  # fmt: skip

        with make_session_factory(engine)() as session:
            rng = random.Random(args.seed)  # noqa: S311 - reproducible demo data, not crypto
            summary = _seed(session, args.company, now, rng)
            session.commit()
    finally:
        engine.dispose()

    print(
        f"Seeded SYNTHETIC history for {args.company}: {summary['synthetic_postings']} postings, "
        f"{summary['snapshots']} daily snapshots from {summary['first_snapshot']:%Y-%m-%d}; "
        f"London spike in the week of {summary['spike_week']}."
    )
    print("Next: uv run python scripts/run_harmonize.py && uv run python scripts/run_detect.py")
    return EXIT_OK
