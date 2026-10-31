"""Which ISO weeks did scraping cover well enough to count new openings?

A week is measurable only when every interval between consecutive ``ok`` snapshots that
touches it is short relative to the company's own cadence, including the time before the
first and after the last snapshot. A Tuesday-to-Sunday outage therefore hides that week AND
the week whose first scrape catches the backlog. Weeks containing a suspect snapshot are
hidden too: a bulk re-import (many ids replaced at once) or a collapsed board (an ``ok`` fetch
that suddenly lists far fewer postings) is an ATS artefact, not hiring or a freeze.
"""

import itertools
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

from jobsignal.weeks import week_start

WEEK = timedelta(days=7)


class SnapshotStat(NamedTuple):
    fetched_at: datetime
    posting_count: int
    new_count: int  # postings first seen at this snapshot


def available_weeks(
    stats: list[SnapshotStat],
    gap_factor: float = 1.5,
    min_gap: timedelta = timedelta(hours=48),
    suspect_new_share: float = 0.5,
    suspect_drop_share: float = 0.5,
) -> set[date]:
    snapshots = sorted(stats)
    if len(snapshots) < 2:
        return set()
    times = [s.fetched_at for s in snapshots]
    gaps = [b - a for a, b in itertools.pairwise(times)]
    allowed = max(min_gap, gap_factor * statistics.median(gaps))

    bad: list[tuple[datetime | None, datetime | None]] = [(None, times[0]), (times[-1], None)]
    bad += [(a, b) for a, b in itertools.pairwise(times) if b - a > allowed]

    suspect_weeks = set()
    for previous, current in itertools.pairwise(snapshots):
        if previous.posting_count <= 0:
            continue
        # a re-import swaps ids: many new ids AND as many old ids vanishing at once
        # (a genuine hiring spurt adds new ids without closing the existing ones)
        closed = previous.posting_count + current.new_count - current.posting_count
        threshold = suspect_new_share * previous.posting_count
        reimport = current.new_count >= threshold and closed >= threshold
        collapse = current.posting_count < suspect_drop_share * previous.posting_count
        if reimport or collapse:
            suspect_weeks.add(week_start(current.fetched_at))

    weeks = set()
    candidate = week_start(times[0])
    while candidate <= week_start(times[-1]):
        start = datetime(candidate.year, candidate.month, candidate.day, tzinfo=UTC)
        end = start + WEEK
        touched = any((a is None or a < end) and (b is None or b > start) for a, b in bad)
        if not touched and candidate not in suspect_weeks:
            weeks.add(candidate)
        candidate += WEEK
    return weeks
