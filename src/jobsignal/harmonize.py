"""Classify stored postings into the canonical role/location taxonomy.

    uv run python scripts/run_harmonize.py [--db URL] [--batch-size N]

Processes every posting whose taxonomy_version is missing or older than the current
TAXONOMY_VERSION, committing per batch. Re-running at the same version does nothing.
Exit codes: 0 done; 2 database schema missing (run ``alembic upgrade head``).
"""

import argparse
import logging
from collections import Counter
from datetime import UTC, datetime

from jobsignal.config import get_settings
from jobsignal.harmonization import taxonomy
from jobsignal.harmonization.locations import parse_locations
from jobsignal.harmonization.roles import classify_title
from jobsignal.harmonization.taxonomy import RoleFamily
from jobsignal.logger import setup_logging
from jobsignal.storage.db import make_engine, make_session_factory, schema_ready
from jobsignal.storage.repository import postings_to_harmonize, save_harmonization

logger = logging.getLogger(__name__)

EXIT_OK, EXIT_NO_SCHEMA = 0, 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harmonize stored postings.")
    parser.add_argument("--db", default=None, help="database URL (default: JOBSIGNAL_DATABASE_URL)")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--log-level", default=None, help="overrides JOBSIGNAL_LOG_LEVEL")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    setup_logging(args.log_level)
    engine = make_engine(args.db or get_settings().database_url)
    try:
        if not schema_ready(engine):
            logger.error("database schema missing; run: uv run alembic upgrade head")
            return EXIT_NO_SCHEMA
        _harmonize(engine, args.batch_size)
        return EXIT_OK
    finally:
        engine.dispose()


def _harmonize(engine, batch_size: int) -> None:
    version = taxonomy.TAXONOMY_VERSION  # read at call time: a bump reprocesses everything
    done = other = 0
    unresolved: Counter[str] = Counter()
    with make_session_factory(engine)() as session:
        while batch := postings_to_harmonize(session, version, batch_size):
            now = datetime.now(UTC)
            for posting in batch:
                roles = classify_title(posting.title, posting.department)
                places = parse_locations(posting.location_raw)
                save_harmonization(session, posting, roles, places, version, now)
                other += roles.family is RoleFamily.OTHER
                unresolved.update(places.unresolved)
            session.commit()
            done += len(batch)

    share = f"{other / done:.1%}" if done else "n/a"
    logger.info(
        "harmonize finished version=%s harmonized=%d other_family=%s unresolved_pieces=%d "
        "top_unresolved=%s",
        version,
        done,
        share,
        sum(unresolved.values()),
        [piece for piece, _ in unresolved.most_common(5)],
    )
