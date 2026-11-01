import json

from jobsignal.api.schemas import CountOut
from jobsignal.dashboard.alerts import alerts_frame, group_alerts
from jobsignal.dashboard.charts import BAND_DOMAIN, composition_chart, trend_chart, z_chart
from tests.unit.dashboard.test_alerts import mix, signal, trend


def spec(chart) -> dict:
    return json.loads(chart.to_json())


def datasets(chart) -> list[list[dict]]:
    """Every data table in the spec: named datasets and inline ``data.values``."""
    body = spec(chart)
    return [*body.get("datasets", {}).values(), *find_all(body, "values")]


def find_all(node, key):
    """Every value stored under ``key`` anywhere in a Vega-Lite spec."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from find_all(v, key)
    elif isinstance(node, list):
        for item in node:
            yield from find_all(item, key)


def test_z_chart_bands_and_rules():
    frame = alerts_frame(group_alerts([signal(id=1, z=6.2), signal(id=2, z=-3.4)]), {})
    chart = spec(z_chart(frame))
    assert BAND_DOMAIN == ["red", "yellow", "none"]
    assert ["red", "yellow", "none"] in list(find_all(chart, "domain"))
    rule_xs = {row["x"] for rows in chart["datasets"].values() for row in rows if "x" in row}
    assert rule_xs == {-5, -3, 3, 5}


def test_z_chart_skips_unscored_rows():
    frame = alerts_frame(group_alerts([signal(id=1, z=3.2), signal(id=2, z=None)]), {})
    rows = [r for rows in datasets(z_chart(frame)) for r in rows if "z" in r]
    assert [r["z"] for r in rows] == [3.2]


def test_trend_chart_keeps_gaps():
    chart = trend_chart(trend(1, [2.0, None, 12.0], [0.5, None, 3.2]), signal(id=1))
    rows = [r for rows in datasets(chart) for r in rows if "value" in r]
    assert [r["value"] for r in rows] == [2.0, None, 12.0]  # a gap, never 0
    y_rules = {row["y"] for rows in datasets(chart) for row in rows if "y" in row}
    assert y_rules == {-5, -3, 3, 5}


def test_trend_chart_baseline_band_for_volume_only():
    volume = spec(trend_chart(trend(1, [2.0, 3.0], [0.5, 1.0]), signal(id=1)))
    bands = [r for rows in volume["datasets"].values() for r in rows if "low" in r]
    assert bands
    assert bands[0]["low"] == 3.14 - 3 * 1.2
    assert bands[0]["high"] == 3.14 + 3 * 1.2
    share = spec(trend_chart(trend(2, [0.1, 0.12], [0.5, 1.0], "share"), mix(id=2)))
    assert not [r for rows in share["datasets"].values() for r in rows if "low" in r]


def test_composition_chart_labels_unclassified():
    chart = composition_chart(
        [CountOut(key="sales", count=3), CountOut(key=None, count=1)], "Role family"
    )
    rows = [r for rows in datasets(chart) for r in rows]
    assert {(r["label"], r["count"]) for r in rows} == {("sales", 3), ("unclassified", 1)}
