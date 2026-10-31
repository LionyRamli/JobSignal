"""Weekly opening counts per cell, with weeks that have no trustworthy data marked missing."""

from datetime import date, datetime, timedelta

import pandas as pd

from jobsignal.signals.params import LEVELS
from jobsignal.weeks import week_start

LEVEL_KEYS: dict[str, list[str]] = {
    "company": ["company"],
    "company_family": ["company", "role_family"],
    "company_country": ["company", "country"],
    "company_family_country": ["company", "role_family", "country"],
}
if tuple(LEVEL_KEYS) != LEVELS:  # keep the two definitions in step
    raise RuntimeError("LEVEL_KEYS and params.LEVELS disagree")


def scored_weeks(as_of: datetime, n: int) -> list[date]:
    """The ``n`` most recent COMPLETE ISO weeks before ``as_of``, oldest first.

    The week containing ``as_of`` is still in progress and is never scored: its partial count
    would look like a slump.
    """
    current = week_start(as_of)
    return [current - timedelta(weeks=k) for k in range(n, 0, -1)]


def cell_counts(
    events: pd.DataFrame,
    level: str,
    weeks: list[date],
    available: dict[str, set[date]] | None,
) -> pd.DataFrame:
    """Distinct postings per cell and week over ``weeks``.

    Every cell with at least one event inside ``weeks`` gets a row for every week:
    ``count`` is zero-filled where the company's week is available, NaN where it is not
    (outage / partial-only week). ``available=None`` treats every week as available.
    """
    if level not in LEVEL_KEYS:
        raise ValueError(f"unknown level {level!r}; expected one of {LEVELS}")
    keys = LEVEL_KEYS[level]
    in_window = events[events["event_week"].isin(weeks)]
    if in_window.empty:
        empty_index = pd.MultiIndex.from_tuples([], names=[*keys, "week"])
        return pd.DataFrame({"count": [], "available": []}, index=empty_index).astype(
            {"count": float, "available": bool}
        )

    counted = in_window.groupby([*keys, "event_week"])["posting_id"].nunique()
    cells = counted.reset_index()[keys].drop_duplicates().itertuples(index=False, name=None)
    grid = pd.MultiIndex.from_tuples(
        [(*cell, week) for cell in cells for week in weeks], names=[*keys, "week"]
    )
    counted.index = counted.index.set_names([*keys, "week"])
    frame = counted.reindex(grid, fill_value=0).astype(float).to_frame("count")

    companies = frame.index.get_level_values("company")
    week_values = frame.index.get_level_values("week")
    if available is None:
        frame["available"] = True
    else:
        frame["available"] = [
            week in available.get(company, set())
            for company, week in zip(companies, week_values, strict=True)
        ]
    frame.loc[~frame["available"], "count"] = float("nan")
    return frame
