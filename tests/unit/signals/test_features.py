import math
from datetime import UTC, date, datetime, timedelta, timezone

import pandas as pd
import pytest

from jobsignal.signals.events import COLUMNS
from jobsignal.signals.features import cell_counts, scored_weeks
from jobsignal.weeks import week_start

W1, W2, W3 = date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)


def events(*rows):
    return pd.DataFrame.from_records(rows, columns=COLUMNS)


def at(frame, *key):
    return frame.loc[key]


def test_week_start_is_monday_utc():
    assert week_start(datetime(2026, 10, 7, 12, tzinfo=UTC)) == W1
    # Sunday 23:30 at -04:00 is Monday 03:30 UTC -> next week
    assert week_start(datetime(2026, 10, 11, 23, 30, tzinfo=timezone(timedelta(hours=-4)))) == W2


def test_partial_week_is_not_scored():
    wednesday = datetime(2026, 11, 4, 15, tzinfo=UTC)
    assert scored_weeks(wednesday, 3) == [
        date(2026, 10, 12),
        date(2026, 10, 19),
        date(2026, 10, 26),
    ]
    monday_midnight = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)  # the new week has just begun
    assert scored_weeks(monday_midnight, 1) == [date(2026, 10, 26)]


def test_counts_distinct_postings_per_cell():
    ev = events(
        (1, "acme", "sales", "US", W1),
        (1, "acme", "sales", "US", W1),
        (2, "acme", "sales", "US", W1),
    )
    counts = cell_counts(ev, "company_family_country", [W1], None)
    assert at(counts, "acme", "sales", "US", W1)["count"] == 2


def test_zero_filled_weeks():
    ev = events((1, "acme", "sales", "US", W1), (2, "acme", "sales", "US", W3))
    counts = cell_counts(ev, "company_family", [W1, W2, W3], None)
    assert counts.xs(("acme", "sales"))["count"].tolist() == [1, 0, 1]
    assert counts["available"].all()


def test_outage_week_is_missing_not_zero():
    ev = events((1, "acme", "sales", "US", W1), (2, "acme", "sales", "US", W3))
    counts = cell_counts(ev, "company", [W1, W2, W3], {"acme": {W1, W3}})
    row = at(counts, "acme", W2)
    assert not row["available"]
    assert math.isnan(row["count"])


def test_levels_aggregate_correctly():
    ev = events(
        (1, "acme", "sales", "US", W1),
        (1, "acme", "sales", "GB", W1),  # multi-country posting
        (2, "acme", "sales", "US", W1),
        (3, "acme", "data", "US", W1),
        (4, "beta", "sales", "US", W1),
    )
    weeks = [W1]
    assert at(cell_counts(ev, "company", weeks, None), "acme", W1)["count"] == 3
    assert at(cell_counts(ev, "company_family", weeks, None), "acme", "sales", W1)["count"] == 2
    assert at(cell_counts(ev, "company_country", weeks, None), "acme", "US", W1)["count"] == 3
    assert at(cell_counts(ev, "company_country", weeks, None), "acme", "GB", W1)["count"] == 1
    full = cell_counts(ev, "company_family_country", weeks, None)
    assert len(full) == 4  # acme/sales/US, acme/sales/GB, acme/data/US, beta/sales/US


def test_cells_need_an_event_inside_the_window():
    ev = events((1, "acme", "sales", "US", date(2026, 1, 5)), (2, "acme", "data", "US", W1))
    counts = cell_counts(ev, "company_family", [W1], None)
    assert list(counts.index) == [("acme", "data", W1)]


def test_empty_events_give_empty_frame():
    counts = cell_counts(events(), "company", [W1], None)
    assert counts.empty
    assert list(counts.columns) == ["count", "available"]


def test_unknown_level_rejected():
    with pytest.raises(ValueError, match="level"):
        cell_counts(events(), "galaxy", [W1], None)
