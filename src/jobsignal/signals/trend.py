"""Trajectories for the dashboard: weekly company series and per-signal trends."""

from collections import defaultdict
from datetime import date, datetime, timedelta

from jobsignal.signals.coverage import SnapshotStat, available_weeks
from jobsignal.weeks import week_start

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
