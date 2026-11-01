from datetime import UTC, date, datetime, timedelta

import pytest

from jobsignal.api.schemas import (
    Company,
    CompanyTrend,
    CompanyTrendPoint,
    SignalOut,
    SignalRunOut,
)
from jobsignal.dashboard.trends import (
    COMPANY_COLUMNS,
    company_frame,
    delta_prev,
    delta_vs_baseline,
    previous_week_run,
    sparkline,
)
from tests.unit.dashboard.test_alerts import mix, signal, trend

NOW = datetime(2026, 11, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1, None, 4, 7], 3),
        ([1, None, 7], 6),
        ([None, 5], None),
        ([5, None], None),
        ([5], None),
        ([], None),
    ],
)
def test_deltas_skip_gaps(values, expected):
    assert delta_prev(values) == expected


def test_sparkline_keeps_gaps():
    assert sparkline(trend(1, [2.0, None, 3.0], [None, None, 1.0])) == [2.0, None, 3.0]


def test_delta_vs_baseline():
    assert delta_vs_baseline(signal(observed=12.0, baseline_mean=3.1)) == pytest.approx(8.9)
    assert delta_vs_baseline(mix()) == pytest.approx(8.2)  # percentage points
    assert delta_vs_baseline(signal(baseline_mean=None)) is None
    assert delta_vs_baseline(mix(share_baseline=None)) is None


def run(run_id, as_of) -> SignalRunOut:
    return SignalRunOut(
        id=run_id, computed_at=as_of, as_of=as_of, signals_version="s", taxonomy_version="t",
        params={},
    )  # fmt: skip


def test_previous_week_run_skips_runs_in_the_same_week():
    mon_19 = run(1, datetime(2026, 10, 19, 12, tzinfo=UTC))
    tue_27 = run(2, datetime(2026, 10, 27, 9, tzinfo=UTC))
    wed_28 = run(3, datetime(2026, 10, 28, 9, tzinfo=UTC))
    assert previous_week_run([wed_28, tue_27, mon_19], wed_28) == mon_19
    assert previous_week_run([mon_19, wed_28, tue_27], tue_27) == mon_19


def test_previous_week_run_none_without_an_older_week():
    only = run(1, datetime(2026, 10, 28, 9, tzinfo=UTC))
    same_week = run(2, datetime(2026, 10, 27, 9, tzinfo=UTC))
    assert previous_week_run([only], only) is None
    assert previous_week_run([only, same_week], only) is None


def company_trend(token, opens, news=None) -> CompanyTrend:
    news = news or [None] * len(opens)
    weeks = [date(2026, 10, 26) - timedelta(weeks=k) for k in range(len(opens) - 1, -1, -1)]
    return CompanyTrend(
        board_token=token,
        points=[CompanyTrendPoint(week_start=w, open_postings=o, new_postings=n)
                for w, o, n in zip(weeks, opens, news, strict=True)],
    )  # fmt: skip


def test_company_frame_delta_and_gaps():
    companies = [
        Company(board_token="acme", source="greenhouse", open_postings=12,
                last_snapshot_at=NOW - timedelta(hours=1), last_snapshot_status="ok"),
        Company(board_token="beta", source="greenhouse", open_postings=3,
                last_snapshot_at=None, last_snapshot_status=None),
    ]  # fmt: skip
    trends = [company_trend("acme", [None, 10, 12], [None, None, 4]), company_trend("beta", [3])]
    frame = company_frame(companies, trends, NOW)
    assert list(frame.columns) == COMPANY_COLUMNS == [
        "company", "open_postings", "d_open_prev_week", "open_trend", "new_trend",
        "last_scrape", "status", "stale",
    ]  # fmt: skip
    acme, beta = frame.iloc[0], frame.iloc[1]
    assert acme["d_open_prev_week"] == 2
    assert acme["open_trend"] == [None, 10, 12]
    assert acme["new_trend"] == [None, None, 4]
    assert not acme["stale"]
    assert beta["d_open_prev_week"] is None
    assert beta["stale"]


def test_company_frame_company_without_trend():
    companies = [
        Company(board_token="gamma", source="greenhouse", open_postings=0,
                last_snapshot_at=None, last_snapshot_status=None),
    ]  # fmt: skip
    row = company_frame(companies, [], NOW).iloc[0]
    assert row["open_trend"] == []
    assert row["d_open_prev_week"] is None


def test_signal_out_factory_is_valid():
    assert isinstance(signal(), SignalOut)
