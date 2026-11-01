"""Trajectories for the dashboard: weekly company series and per-signal trends."""

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

import pandas as pd
from sqlalchemy.orm import Session

from jobsignal.signals.coverage import SnapshotStat, available_weeks
from jobsignal.signals.detectors import mix_shift_scores, volume_scores
from jobsignal.signals.events import to_frame
from jobsignal.signals.features import cell_counts, scored_weeks
from jobsignal.signals.params import DetectorParams
from jobsignal.storage.repository import ok_snapshot_stats, opening_rows
from jobsignal.storage.schema import SignalRun, SignalScore
from jobsignal.weeks import week_start

TREND_WEEKS = 8

CompanyPoint = tuple[date, int | None, int | None]  # week_start, open_postings, new_postings


def company_trends(
    stats: dict[str, list[tuple[datetime, int, int]]],
    tokens: list[str],
    now: datetime,
    weeks: int,
) -> list[tuple[str, list[CompanyPoint]]]:
    """Per company, the ``weeks`` ISO weeks ending with the current one, oldest first.

    open_postings: posting_count of the week's last ok snapshot (None without one).
    new_postings: postings first seen at that week's ok snapshots, only for weeks whose
    coverage is trustworthy (signals.coverage); otherwise None, which also hides the
    initial-load spike of the first snapshot's week.
    """
    current = week_start(now)
    window = [current - timedelta(weeks=k) for k in range(weeks - 1, -1, -1)]
    result = []
    for token in tokens:
        snapshots = sorted(stats.get(token, []))
        covered = available_weeks([SnapshotStat(*s) for s in snapshots])
        last_open: dict[date, int] = {}
        new: dict[date, int] = defaultdict(int)
        for fetched_at, posting_count, new_count in snapshots:
            week = week_start(fetched_at)
            last_open[week] = posting_count
            new[week] += new_count
        points = [
            (week, last_open.get(week), new[week] if week in covered else None) for week in window
        ]
        result.append((token, points))
    return result


class TrendPoint(NamedTuple):
    week_start: date
    value: float | None  # volume: openings that week; mix_shift: recent-window share
    z: float | None


def _cell_row(scores: pd.DataFrame, role_family: str | None, country: str | None):
    mask = pd.Series(True, index=scores.index)
    for column, value in (("role_family", role_family), ("country", country)):
        if value is not None:
            mask &= scores[column] == value
    matched = scores[mask]
    return None if matched.empty else matched.iloc[0]


def _in_cell(events: pd.DataFrame, role_family: str | None, country: str | None) -> pd.DataFrame:
    mask = pd.Series(True, index=events.index)
    if role_family is not None:
        mask &= events["role_family"] == role_family
    if country is not None:
        mask &= events["country"] == country
    return events[mask]


def _spans(as_of: datetime, detector: str, params: DetectorParams) -> list[date]:
    """The weeks ``detect.score_all`` gives the detector at ``as_of``."""
    if detector == "volume":
        return scored_weeks(as_of, 2 * params.baseline_weeks + 1)
    return scored_weeks(as_of, params.recent_weeks + params.mix_baseline_weeks)


def _weeks_in(counts: pd.DataFrame, span: list[date]) -> pd.DataFrame:
    return counts[counts.index.get_level_values("week").isin(span)]


def cell_trend(
    observed: pd.DataFrame,
    published: pd.DataFrame,
    available: dict[str, set[date]],
    *,
    detector: str,
    level: str,
    company: str,
    role_family: str | None,
    country: str | None,
    week: date,
    params: DetectorParams,
    weeks: int = TREND_WEEKS,
) -> list[TrendPoint]:
    """The cell's last ``weeks`` scored weeks, oldest first, ending at ``week``.

    Each point re-runs the detector as ``detect.score_all`` would with ``as_of`` in the week
    after the point (so the point is the newest complete week): the last point reproduces
    the stored score. Uncovered weeks and absent cells are (None, None), never 0.

    Only the cell's own events are counted (a cell's counts do not depend on other cells;
    mix_shift company totals still use all of the company's events), and they are counted
    once over the union of every point's window, then sliced per point.
    """
    events = observed if detector == "volume" else published
    company_events = events[events["company"] == company]
    cell_events = _in_cell(company_events, role_family, country)
    cell_weeks = set(cell_events["event_week"])

    def as_of_for(point_week: date) -> datetime:
        midnight = datetime(point_week.year, point_week.month, point_week.day, tzinfo=UTC)
        return midnight + timedelta(days=7)

    point_weeks = [week - timedelta(weeks=k) for k in range(weeks - 1, -1, -1)]
    first_span = _spans(as_of_for(point_weeks[0]), detector, params)
    union = sorted(set(first_span) | set(_spans(as_of_for(week), detector, params)))
    union = [w for w in union if w >= first_span[0]]
    if detector == "volume":
        cell_all = cell_counts(cell_events, level, union, available)
        company_all = None
    else:
        cell_all = cell_counts(cell_events, level, union, None)
        company_all = cell_counts(company_events, "company", union, None)

    points = []
    for point_week in point_weeks:
        span = _spans(as_of_for(point_week), detector, params)
        if not cell_weeks.intersection(span):  # the detector never sees this cell here
            points.append(TrendPoint(point_week, None, None))
            continue
        cell = _weeks_in(cell_all, span)
        if detector == "volume":
            scores = volume_scores(cell, params)
        else:
            scores = mix_shift_scores(cell, _weeks_in(company_all, span), level, params)
        row = None if scores.empty else _cell_row(scores, role_family, country)
        if row is None:
            points.append(TrendPoint(point_week, None, None))
            continue
        if detector == "volume":
            value = float(row["observed"])
        else:
            total = row["company_recent_total"]
            value = float(row["observed"]) / float(total) if total else None
        z = None if row["z"] is None else float(row["z"])
        points.append(TrendPoint(point_week, value, z))
    return points


def trends_for_scores(
    session: Session, scores: list[tuple[SignalScore, str, SignalRun]]
) -> dict[int, list[TrendPoint]]:
    """Trends for stored scores, each recomputed from the data its run could see.

    Postings first seen and snapshots fetched after the run's ``computed_at`` are left out,
    so a later scrape (e.g. a backdated published date) cannot move the trend away from the
    stored score. Events load once per company and coverage once in total. Role families are
    read as they are now (like the drill-down), so runs scored under an older taxonomy can
    differ slightly.
    """
    if not scores:
        return {}
    stats = ok_snapshot_stats(session)
    rows_by_company: dict[str, list] = {}
    frames: dict[tuple[str, datetime], tuple[pd.DataFrame, pd.DataFrame]] = {}
    coverage: dict[datetime, dict[str, set[date]]] = {}
    result = {}
    for score, company, run in scores:
        cutoff = run.computed_at
        if cutoff not in coverage:
            coverage[cutoff] = {
                token: available_weeks(
                    [SnapshotStat(*stat) for stat in snapshots if stat[0] <= cutoff]
                )
                for token, snapshots in stats.items()
            }
        if company not in rows_by_company:
            rows_by_company[company] = opening_rows(session, company=company)
        if (company, cutoff) not in frames:
            seen = [row for row in rows_by_company[company] if row.first_seen_at <= cutoff]
            frames[company, cutoff] = (to_frame(seen, "observed"), to_frame(seen, "published"))
        observed, published = frames[company, cutoff]
        available = coverage[cutoff]
        result[score.id] = cell_trend(
            observed,
            published,
            available,
            detector=score.detector,
            level=score.level,
            company=company,
            role_family=score.role_family,
            country=score.country_code,
            week=score.week_start,
            params=DetectorParams(**json.loads(run.params)),
        )
    return result
