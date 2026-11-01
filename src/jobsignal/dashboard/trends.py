"""Trajectory maths for the dashboard: sparklines and deltas. Gaps stay gaps (None)."""

from collections.abc import Sequence
from datetime import datetime, timedelta

import pandas as pd

from jobsignal.api.schemas import Company, CompanyTrend, SignalOut, SignalRunOut, SignalTrend
from jobsignal.weeks import week_start

STALE_AFTER = timedelta(hours=36)
COMPANY_COLUMNS = [
    "company", "open_postings", "d_open_prev_week", "open_trend", "new_trend",
    "last_scrape", "status", "stale",
]  # fmt: skip


def sparkline(trend: SignalTrend) -> list[float | None]:
    return [p.value for p in trend.points]


def delta_prev(values: Sequence[float | None]) -> float | None:
    """Last value minus the nearest earlier known value; None if either is unknown."""
    if not values or values[-1] is None:
        return None
    earlier = [v for v in values[:-1] if v is not None]
    return values[-1] - earlier[-1] if earlier else None


def delta_vs_baseline(s: SignalOut) -> float | None:
    """Volume: observed - baseline mean. Mix: share change in percentage points."""
    if s.detector == "mix_shift":
        if s.share_recent is None or s.share_baseline is None:
            return None
        return (s.share_recent - s.share_baseline) * 100
    if s.observed is None or s.baseline_mean is None:
        return None
    return s.observed - s.baseline_mean


def previous_week_run(runs: Sequence[SignalRunOut], current: SignalRunOut) -> SignalRunOut | None:
    """The newest run that scored an earlier week than ``current`` (daily runs share a week)."""
    this_week = week_start(current.as_of)
    older = [r for r in runs if r.as_of < current.as_of and week_start(r.as_of) < this_week]
    return max(older, key=lambda r: (r.as_of, r.id), default=None)


def stale_companies(companies: Sequence[Company], now: datetime) -> list[str]:
    """Tokens whose last scrape is missing, older than STALE_AFTER, or not ok."""
    return [
        c.board_token
        for c in companies
        if c.last_snapshot_at is None
        or c.last_snapshot_status != "ok"
        or now - c.last_snapshot_at > STALE_AFTER
    ]


def company_frame(
    companies: Sequence[Company], trends: Sequence[CompanyTrend], now: datetime
) -> pd.DataFrame:
    by_token = {t.board_token: t for t in trends}
    stale = set(stale_companies(companies, now))
    rows = []
    for c in companies:
        trend = by_token.get(c.board_token)
        opens = [p.open_postings for p in trend.points] if trend else []
        rows.append(
            {
                "company": c.board_token,
                "open_postings": c.open_postings,
                "d_open_prev_week": delta_prev(opens),
                "open_trend": opens,
                "new_trend": [p.new_postings for p in trend.points] if trend else [],
                "last_scrape": c.last_snapshot_at,
                "status": c.last_snapshot_status,
                "stale": c.board_token in stale,
            }
        )
    return pd.DataFrame(rows, columns=COMPANY_COLUMNS, dtype=object)
