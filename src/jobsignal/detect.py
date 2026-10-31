"""Score hiring per company x role family x country and store a signal run.

    uv run python scripts/run_detect.py [--as-of YYYY-MM-DD] [--db URL]

Pipeline order: scrape -> harmonize -> detect. Each invocation stores a NEW run (append-only).
Detectors: ``volume`` on observed new openings (needs weeks of scrape history) and
``mix_shift`` on ATS published dates (available immediately, provisional).
Exit codes: 0 done; 2 database schema missing or bad arguments.
"""

import argparse
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

import pandas as pd

from jobsignal.config import get_settings
from jobsignal.logger import setup_logging
from jobsignal.signals.coverage import SnapshotStat, available_weeks
from jobsignal.signals.detectors import SCORE_COLUMNS, mix_shift_scores, volume_scores
from jobsignal.signals.events import to_frame
from jobsignal.signals.features import cell_counts, scored_weeks
from jobsignal.signals.params import LEVELS, DetectorParams
from jobsignal.storage.db import make_engine, make_session_factory, schema_ready
from jobsignal.storage.repository import ok_snapshot_stats, opening_rows, save_signal_run

logger = logging.getLogger(__name__)

EXIT_OK, EXIT_NO_SCHEMA = 0, 2


def _as_of_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}") from None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect hiring anomalies.")
    parser.add_argument("--as-of", type=_as_of_date, default=None,
                        help="score complete weeks before this date (default: now)")  # fmt: skip
    parser.add_argument("--db", default=None, help="database URL (default: JOBSIGNAL_DATABASE_URL)")
    parser.add_argument("--log-level", default=None, help="overrides JOBSIGNAL_LOG_LEVEL")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, now: Callable[[], datetime] | None = None) -> int:
    args = _parse_args(argv)
    setup_logging(args.log_level)
    clock = now or (lambda: datetime.now(UTC))
    computed_at = clock()
    as_of = datetime(*args.as_of.timetuple()[:3], tzinfo=UTC) if args.as_of else computed_at

    engine = make_engine(args.db or get_settings().database_url)
    try:
        if not schema_ready(engine):
            logger.error("database schema missing; run: uv run alembic upgrade head")
            return EXIT_NO_SCHEMA
        with make_session_factory(engine)() as session:
            scores = score_all(session, as_of, DetectorParams())
            run = save_signal_run(session, computed_at, as_of, DetectorParams(), scores)
            session.commit()
            _log_summary(run.id, scores)
        return EXIT_OK
    finally:
        engine.dispose()


def score_all(session, as_of: datetime, params: DetectorParams) -> pd.DataFrame:
    rows = opening_rows(session)
    observed, published = to_frame(rows, "observed"), to_frame(rows, "published")
    # Only weeks that scraping covered continuously count (no outage gap, re-import or
    # collapsed board). The first-snapshot week is never covered: it starts before the
    # first scrape, so its count of 'new' openings is ~0 by construction.
    available = {
        company: available_weeks([SnapshotStat(*stat) for stat in stats])
        for company, stats in ok_snapshot_stats(session).items()
    }

    # extra history lets the baseline skip up to `baseline_weeks` missing (outage) weeks
    volume_weeks = scored_weeks(as_of, 2 * params.baseline_weeks + 1)
    mix_weeks = scored_weeks(as_of, params.recent_weeks + params.mix_baseline_weeks)
    company_published = cell_counts(published, "company", mix_weeks, None)

    parts = []
    for level in LEVELS:
        volume = volume_scores(cell_counts(observed, level, volume_weeks, available), params)
        parts.append(volume.assign(basis="observed", level=level))
        mix = mix_shift_scores(
            cell_counts(published, level, mix_weeks, None), company_published, level, params
        )
        parts.append(mix.assign(basis="published", level=level))
    parts = [part for part in parts if not part.empty]  # cold start yields empty frames
    if not parts:
        return pd.DataFrame(columns=[*SCORE_COLUMNS, "basis", "level"])
    return pd.concat(parts, ignore_index=True)


def _log_summary(run_id: int, scores: pd.DataFrame) -> None:
    signals = scores[scores["is_signal"].astype(bool)]
    by_status = scores.groupby(["detector", "status"]).size().to_dict() if len(scores) else {}
    by_direction = signals.groupby("direction").size().to_dict() if len(signals) else {}
    top = signals.assign(abs_z=signals["z"].astype(float).abs()).nlargest(5, "abs_z")
    described = [
        f"{r.company}/{r.level}/{r.role_family or '-'}/{r.country or '-'} z={float(r.z):+.2f}"
        for r in top.itertuples()
    ]
    logger.info(
        "detect finished run_id=%d rows=%d by_status=%s signals=%d by_direction=%s top=%s",
        run_id,
        len(scores),
        by_status,
        len(signals),
        by_direction,
        described,
    )
