from datetime import UTC, date, datetime, timedelta

import pytest

from jobsignal.api.schemas import Company, SignalOut, SignalTrend, TrendPointOut
from jobsignal.dashboard.alerts import (
    ALERT_COLUMNS,
    alerts_frame,
    cell_label,
    describe,
    group_alerts,
    safe_url,
    stale_companies,
    z_band,
)

WEEK = date(2026, 10, 12)


def signal(**overrides) -> SignalOut:
    fields = {
        "id": 1, "run_id": 1, "detector": "volume", "basis": "observed",
        "level": "company_family_country", "company": "acme", "role_family": "sales",
        "country_code": "GB", "week_start": WEEK, "observed": 12.0, "baseline_mean": 3.14,
        "baseline_std": 1.2, "baseline_weeks": 8, "z": 3.2, "status": "scored",
        "is_signal": True, "direction": "expansion", "severity": "notable",
        "share_recent": None, "share_baseline": None, "provisional": False,
    }  # fmt: skip
    fields.update(overrides)
    return SignalOut(**fields)


def mix(**overrides) -> SignalOut:
    fields = {
        "detector": "mix_shift", "basis": "published", "level": "company_family",
        "company": "anthropic", "role_family": "solutions_engineering", "country_code": "US",
        "observed": 31.0, "baseline_mean": 30.0, "share_recent": 0.124,
        "share_baseline": 0.042, "z": 3.27, "provisional": True,
    }  # fmt: skip
    fields.update(overrides)
    return signal(**fields)


@pytest.mark.parametrize(
    ("z", "band"),
    [(None, "none"), (0.0, "none"), (2.99, "none"), (-2.99, "none"), (3.0, "yellow"),
     (-3.0, "yellow"), (5.0, "yellow"), (-5.0, "yellow"), (5.01, "red"), (-7.2, "red")],
)  # fmt: skip
def test_z_band(z, band):
    assert z_band(z) == band


def test_cell_label():
    assert cell_label(signal(level="company", role_family=None, country_code=None)) == (
        "all roles · all countries"
    )
    assert cell_label(signal()) == "sales · GB"


def test_describe_volume():
    assert describe(signal()) == (
        "acme · sales · GB: 12 new postings in the week of 2026-10-12 vs a baseline of "
        "3.1 ± 1.2 (z = +3.20)"
    )


def test_describe_mix():
    assert describe(mix()) == (
        "anthropic · solutions_engineering · US: 12.4% of recent postings vs 4.2% in the "
        "baseline (z = +3.27, provisional)"
    )


def test_describe_not_scored():
    text = describe(
        signal(company="beta", level="company", role_family=None, country_code=None, z=None,
               baseline_mean=None, baseline_std=None, status="insufficient_history")
    )  # fmt: skip
    assert text == "beta · all roles · all countries: not scored (insufficient_history)"
    assert "nan" not in text
    assert "None" not in text


def test_group_alerts_merges_levels_and_picks_headline():
    rows = [
        signal(id=1, level="company", role_family=None, country_code=None, z=3.5),
        signal(id=2, level="company_family", country_code=None, z=3.5),
        signal(id=3, level="company_family_country", z=3.1),
        signal(id=4, level="company", role_family=None, country_code=None, z=-4.0,
               direction="contraction"),
        signal(id=5, company="beta", level="company", role_family=None, country_code=None,
               z=6.0),
    ]  # fmt: skip
    groups = group_alerts(rows)
    assert [g.headline.z for g in groups] == [6.0, -4.0, 3.5]
    acme = groups[2]
    assert acme.headline.level == "company_family"  # tie on |z|: the more specific level
    assert [r.level for r in acme.related] == ["company", "company_family_country"]


def test_group_alerts_null_z_rows_are_singletons_last():
    rows = [
        signal(id=7, z=None, level="company", role_family=None, country_code=None),
        signal(id=8, z=None, level="company_family", country_code=None),
        signal(id=9, z=3.1),
    ]  # fmt: skip
    groups = group_alerts(rows)
    assert [g.headline.id for g in groups] == [9, 7, 8]
    assert all(g.related == () for g in groups)


def test_group_alerts_empty():
    assert group_alerts([]) == []


def company(token, at, status="ok"):
    return Company(
        board_token=token, source="greenhouse", open_postings=1, last_snapshot_at=at,
        last_snapshot_status=status,
    )  # fmt: skip


def test_stale_companies():
    now = datetime(2026, 11, 1, 12, tzinfo=UTC)
    companies = [
        company("fresh", now - timedelta(hours=2)),
        company("old", now - timedelta(hours=37)),
        company("partial", now - timedelta(hours=1), status="partial"),
        company("never", None, status=None),
    ]
    assert stale_companies(companies, now) == ["old", "partial", "never"]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://boards.greenhouse.io/x", "https://boards.greenhouse.io/x"),
        ("HTTP://a.b", "HTTP://a.b"),
        ("javascript:alert(1)", None),
        (" javascript:alert(1)", None),
        ("data:text/html,x", None),
        ("", None),
        (None, None),
    ],
)
def test_safe_url(url, expected):
    assert safe_url(url) == expected


def trend(signal_id, values, zs, metric="count"):
    weeks = [WEEK - timedelta(weeks=k) for k in range(len(values) - 1, -1, -1)]
    return SignalTrend(
        signal_id=signal_id, metric=metric,
        points=[TrendPointOut(week_start=w, value=v, z=z)
                for w, v, z in zip(weeks, values, zs, strict=True)],
    )  # fmt: skip


def test_alerts_frame_columns_trend_and_dz():
    groups = group_alerts([signal(id=1, z=3.2), mix(id=2)])
    trends = {1: trend(1, [2.0, None, 3.0, 12.0], [0.1, None, 1.0, 3.2])}
    frame = alerts_frame(groups, trends)
    assert list(frame.columns) == ALERT_COLUMNS == [
        "id", "band", "company", "cell", "detector", "direction", "z", "dz_prev_week",
        "observed", "baseline", "d_baseline", "trend", "week", "provisional", "also_at",
    ]  # fmt: skip
    by_id = frame.set_index("id")
    assert by_id.loc[1, "trend"] == [2.0, 3.0, 12.0]  # chart cells drop gaps
    assert by_id.loc[1, "dz_prev_week"] == pytest.approx(2.2)
    assert by_id.loc[1, "d_baseline"] == pytest.approx(12.0 - 3.14)
    assert by_id.loc[2, "trend"] == []  # no trend fetched for it
    assert by_id.loc[2, "dz_prev_week"] is None
    assert by_id.loc[2, "observed"] == pytest.approx(0.124)  # mix rows show shares
    assert by_id.loc[2, "baseline"] == pytest.approx(0.042)
    assert by_id.loc[2, "d_baseline"] == pytest.approx(8.2)  # percentage points
    assert by_id.loc[2, "provisional"]
    assert by_id.loc[1, "band"] == "yellow"


def test_alerts_frame_also_at_lists_related_cells():
    groups = group_alerts([
        signal(id=1, level="company", role_family=None, country_code=None, z=3.5),
        signal(id=2, level="company_family", country_code=None, z=3.4),
    ])  # fmt: skip
    frame = alerts_frame(groups, {})
    assert frame.loc[0, "also_at"] == "sales · all countries"


def test_alerts_frame_empty_has_columns():
    assert list(alerts_frame([], {}).columns) == ALERT_COLUMNS
