from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from jobsignal.signals.detectors import mix_shift_scores, volume_scores
from jobsignal.signals.events import COLUMNS
from jobsignal.signals.features import cell_counts, scored_weeks
from jobsignal.signals.params import DetectorParams
from jobsignal.signals.trend import TREND_WEEKS, cell_trend

PARAMS = DetectorParams()
LAST = date(2026, 10, 19)  # a Monday
WEEKS = [LAST - timedelta(weeks=k) for k in range(19, -1, -1)]  # 20 weeks, oldest first
SALES = [3, 4, 3, 5, 4, 3, 4, 5, 3, 4, 3, 4, 5, 4, 3, 4, 5, 3, 4, 15]  # spike in the last week


def events(per_week_sales, other_per_week=10):
    rows, pid = [], 0
    for week, n_sales in zip(WEEKS, per_week_sales, strict=True):
        for family, n in (("sales", n_sales), ("engineering", other_per_week)):
            for _ in range(n):
                pid += 1
                rows.append((pid, "acme", family, "GB", week))
    return pd.DataFrame.from_records(rows, columns=COLUMNS)


def as_of(week):
    return datetime(week.year, week.month, week.day, tzinfo=UTC) + timedelta(days=7)


def all_available():
    return {"acme": set(WEEKS)}


def trend(detector, frame, available=None, week=LAST, level="company_family"):
    return cell_trend(
        frame, frame, available if available is not None else all_available(),
        detector=detector, level=level, company="acme", role_family="sales", country=None,
        week=week, params=PARAMS,
    )  # fmt: skip


def detector_row(scores):
    return scores[scores["role_family"] == "sales"].iloc[0]


def test_last_point_matches_detector_volume():
    frame = events(SALES)
    counts = cell_counts(
        frame, "company_family", scored_weeks(as_of(LAST), 2 * PARAMS.baseline_weeks + 1),
        all_available(),
    )  # fmt: skip
    expected = detector_row(volume_scores(counts, PARAMS))
    last = trend("volume", frame)[-1]
    assert last.week_start == LAST
    assert last.value == expected["observed"] == 15.0
    assert last.z == pytest.approx(expected["z"])
    assert last.z > 3  # the spike is a signal


def test_last_point_matches_detector_mix():
    frame = events(SALES)
    weeks = scored_weeks(as_of(LAST), PARAMS.recent_weeks + PARAMS.mix_baseline_weeks)
    company = cell_counts(frame, "company", weeks, None)
    expected = detector_row(
        mix_shift_scores(cell_counts(frame, "company_family", weeks, None), company,
                         "company_family", PARAMS)
    )  # fmt: skip
    last = trend("mix_shift", frame)[-1]
    share_recent = expected["observed"] / expected["company_recent_total"]
    assert last.value == pytest.approx(share_recent)
    assert last.z == pytest.approx(expected["z"])


def test_previous_point_is_the_detector_one_week_earlier():
    frame = events(SALES)
    previous_week = LAST - timedelta(weeks=1)
    counts = cell_counts(
        frame, "company_family", scored_weeks(as_of(previous_week), 2 * PARAMS.baseline_weeks + 1),
        all_available(),
    )  # fmt: skip
    expected = detector_row(volume_scores(counts, PARAMS))
    point = trend("volume", frame)[-2]
    assert point.week_start == previous_week
    assert (point.value, point.z) == (expected["observed"], pytest.approx(expected["z"]))


def test_trend_has_weeks_points_oldest_first():
    points = trend("volume", events(SALES))
    assert len(points) == TREND_WEEKS == 8
    starts = [p.week_start for p in points]
    assert starts == sorted(starts)
    assert len(set(starts)) == 8
    assert starts[-1] == LAST
    assert starts[0] == LAST - timedelta(weeks=7)


def test_uncovered_week_is_gap():
    gap = LAST - timedelta(weeks=2)
    points = trend("volume", events(SALES), available={"acme": set(WEEKS) - {gap}})
    point = next(p for p in points if p.week_start == gap)
    assert point.value is None
    assert point.z is None  # never 0


def test_cold_start_all_none():
    frame = events(SALES)
    frame = frame[frame["event_week"] >= LAST - timedelta(weeks=2)]  # only 3 weeks of data
    points = trend("volume", frame, available={"acme": set(WEEKS[-3:])})
    assert all(p.z is None for p in points)


def test_absent_cell_is_none_point():
    missing = cell_trend(
        events(SALES), events(SALES), all_available(), detector="volume",
        level="company_family", company="acme", role_family="legal", country=None,
        week=LAST, params=PARAMS,
    )  # fmt: skip
    assert [(p.value, p.z) for p in missing] == [(None, None)] * TREND_WEEKS


def test_scores_only_the_requested_cell(monkeypatch):
    """Perf guard: each point must score one cell, not every cell of the company's level."""
    import jobsignal.signals.trend as trend_module

    real, seen = trend_module.volume_scores, []

    def spy(counts, params):
        names = list(counts.index.names)[:-1]
        seen.append(counts.reset_index()[names].drop_duplicates().shape[0])
        return real(counts, params)

    monkeypatch.setattr(trend_module, "volume_scores", spy)
    trend("volume", events(SALES))  # two families present: sales and engineering
    assert seen
    assert set(seen) == {1}


def test_cell_leaving_the_window_matches_detector():
    """A cell whose events age out of the window is absent (detector skips it), not a 0 score."""
    frame = events(SALES)
    legal = pd.DataFrame.from_records(
        [(10_000 + i, "acme", "legal", "GB", WEEKS[i]) for i in range(3)], columns=COLUMNS
    )
    frame = pd.concat([frame, legal], ignore_index=True)
    points = cell_trend(
        frame, frame, all_available(), detector="volume", level="company_family",
        company="acme", role_family="legal", country=None, week=LAST, params=PARAMS,
    )  # fmt: skip
    for point in points:
        counts = cell_counts(
            frame, "company_family",
            scored_weeks(as_of(point.week_start), 2 * PARAMS.baseline_weeks + 1), all_available(),
        )  # fmt: skip
        scores = volume_scores(counts, PARAMS)
        expected = scores[scores["role_family"] == "legal"]
        if expected.empty:
            assert (point.value, point.z) == (None, None), point
        else:
            row = expected.iloc[0]
            assert point.value == row["observed"]
            assert point.z == (None if row["z"] is None else pytest.approx(row["z"]))
    assert (points[-1].value, points[-1].z) == (None, None)  # events left the window
    assert points[-2].value == 0.0  # still inside the window: a real zero-count week


def test_counts_cells_once_per_trend(monkeypatch):
    """Perf guard: cell_counts runs over the whole span once, not once per point."""
    import jobsignal.signals.trend as trend_module

    real, calls = trend_module.cell_counts, []

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(trend_module, "cell_counts", spy)
    trend("volume", events(SALES))
    assert len(calls) <= 1
    calls.clear()
    trend("mix_shift", events(SALES))
    assert len(calls) <= 2  # the cell and its company totals
