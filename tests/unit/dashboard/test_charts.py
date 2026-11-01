import json
import re

import pytest

from jobsignal.api.schemas import CountOut
from jobsignal.dashboard.alerts import alerts_frame, group_alerts
from jobsignal.dashboard.charts import SLOTS, composition_chart, palette, trend_chart, z_chart
from jobsignal.dashboard.glossary import EN, ZH
from tests.unit.dashboard.test_alerts import mix, signal, trend

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
CJK = re.compile(r"[一-鿿]")


def spec(chart) -> dict:
    return json.loads(chart.to_json())


def styles(body: dict) -> dict:
    """The spec without its data: what is left is presentation."""
    if isinstance(body, dict):
        return {k: styles(v) for k, v in body.items() if k not in ("data", "datasets")}
    if isinstance(body, list):
        return [styles(v) for v in body]
    return body


def datasets(chart) -> list[list[dict]]:
    """Every data table in the spec: named datasets and inline ``data.values``."""
    body = spec(chart)
    inline = [v for v in find_all(body, "values") if v and isinstance(v[0], dict)]  # not legends
    return [*body.get("datasets", {}).values(), *inline]


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


def colour_slots(chart) -> set[str]:
    """The palette slots a chart paints constant-colour marks with."""
    calcs = [t for t in find_all(spec(chart), "transform") for t in t if t.get("as") == "slot"]
    return {t["calculate"].strip("'") for t in calcs}


def frame(copy=EN):
    alerts = [signal(id=1, z=6.2), signal(id=2, z=-3.4, direction="contraction")]
    return alerts_frame(group_alerts(alerts), {}, copy)


def sample_charts(copy=EN):
    return [
        z_chart(frame(copy), copy),
        trend_chart(trend(1, [2.0, None, 12.0], [0.5, None, 3.2]), signal(id=1), copy),
        trend_chart(trend(2, [0.1, 0.12], [0.5, 1.0], "share"), mix(id=2), copy),
        composition_chart(
            [CountOut(key="sales", count=3)], copy.postings_table["role_family"].label, copy=copy
        ),
    ]


ALL_CHARTS = [*sample_charts(EN), *sample_charts(ZH)]


def test_palette_slots_in_theme_order():
    assert SLOTS == ("extreme", "unusual", "below", "series", "ink", "normal")
    # bands show by their translated names; the other slots never reach a legend
    assert palette(EN)[:3] == [EN.band["red"], EN.band["yellow"], EN.band["none"]]
    assert palette(ZH)[:3] == [ZH.band["red"], ZH.band["yellow"], ZH.band["none"]]
    assert palette(EN)[3:] == palette(ZH)[3:] == ["series", "ink", "normal"]


@pytest.mark.parametrize("chart", ALL_CHARTS)
def test_charts_take_every_colour_from_the_theme(chart):
    """No colour of their own: light/dark switches recolour them live, without a rerun."""
    body = styles(spec(chart))
    assert not HEX.search(json.dumps(body))
    for key in ("labelColor", "titleColor", "fill", "stroke"):
        assert all(value is None for value in find_all(body, key)), key
    assert not [m for m in find_all(body, "mark") if isinstance(m, dict) and "color" in m]
    colours = [e["color"] for e in find_all(body, "encoding") if "color" in e]
    assert colours
    for colour in colours:
        assert isinstance(colour, dict), colour  # an encoding, never a literal
        assert colour["scale"]["range"] == "category"  # = the theme's chart palette
        assert colour["scale"]["domain"] in (palette(EN), palette(ZH))


def test_z_chart_bands_and_rules():
    body = spec(z_chart(frame()))
    bands = [r["band"] for rows in datasets(z_chart(frame())) for r in rows if "z" in r]
    assert bands == [EN.band["red"], EN.band["yellow"]]
    legends = [v for v in find_all(body, "legend") if v]
    assert [legend["values"] for legend in legends] == [palette(EN)[:3]]  # bands only
    rule_xs = {row["x"] for rows in datasets(z_chart(frame())) for row in rows if "x" in row}
    assert rule_xs == {-5, -3, 3, 5}


def test_z_chart_keeps_its_band_legend():
    """Layers without a legend share the colour scale unless resolved apart: legend vanishes."""
    assert spec(z_chart(frame()))["resolve"]["scale"]["color"] == "independent"


def test_z_chart_leaves_room_for_value_labels_and_thresholds():
    domain = spec(z_chart(frame()))["layer"][2]["encoding"]["x"]["scale"]["domain"]
    assert domain == [-6, 8]  # z = -3.4 .. 6.2, a unit of room past each end, ±5 always in
    far = alerts_frame(group_alerts([signal(id=1, z=-9.3, direction="contraction")]), {})
    assert spec(z_chart(far))["layer"][2]["encoding"]["x"]["scale"]["domain"] == [-11, 6]


def test_bar_order_is_explicit():
    """Layers with their own transforms cannot merge a '-x' sort: the order is spelled out."""
    counts = [CountOut(key=None, count=2), CountOut(key="sales", count=12),
              CountOut(key="design", count=7)]  # fmt: skip
    chart = spec(composition_chart(counts, "Role family"))
    assert [*find_all(chart, "sort")] == [["Sales", "Design", "Unclassified"]] * 2
    z_sorts = [*find_all(spec(z_chart(frame())), "sort")]
    assert z_sorts
    assert all(s == ["#1 acme · Sales · GB", "#2 acme · Sales · GB"] for s in z_sorts)


def test_value_labels_and_glow_use_theme_slots():
    assert "ink" in colour_slots(z_chart(frame()))  # value at each bar's tip
    chart = trend_chart(trend(1, [2.0, 3.0], [0.5, 1.0]), signal(id=1))
    assert {"series", "normal", "below"} <= colour_slots(chart)
    widths = {m.get("strokeWidth") for m in find_all(spec(chart), "mark") if isinstance(m, dict)}
    assert {2, 8} <= widths  # crisp line over its wide, faint glow


@pytest.mark.parametrize("chart", ALL_CHARTS)
def test_charts_have_no_gridlines_or_frame(chart):
    body = spec(chart)
    grids = list(find_all(body, "grid"))
    assert grids
    assert not any(grids)
    assert body["config"]["view"]["stroke"] is None


@pytest.mark.parametrize("chart", ALL_CHARTS)
def test_tooltips_are_titled_in_plain_words(chart):
    tooltips = [t for group in find_all(spec(chart), "tooltip") for t in group]
    assert tooltips
    for item in tooltips:
        assert item.get("title"), item
        assert not re.search(r"\b[a-z]+_[a-z_]+\b", item["title"]), item


@pytest.mark.parametrize("copy", [EN, ZH], ids=["en", "zh"])
def test_z_chart_tooltip_uses_the_table_names(copy):
    titles = {t["title"] for g in find_all(spec(z_chart(frame(copy), copy)), "tooltip") for t in g}
    assert {copy.alert_table[c].label for c in ("direction", "z", "detector", "band")} <= titles


@pytest.mark.parametrize("chart", sample_charts(ZH))
def test_charts_speak_mandarin(chart):
    body = styles(spec(chart))
    words = [*find_all(body, "title"), *(t["title"] for g in find_all(body, "tooltip") for t in g)]
    words = [w if isinstance(w, str) else w.get("text", "") for w in words if w]
    assert words
    for word in words:
        assert CJK.search(word), word


def test_z_chart_skips_unscored_rows():
    rows_in = alerts_frame(group_alerts([signal(id=1, z=3.2), signal(id=2, z=None)]), {})
    rows = [r for rows in datasets(z_chart(rows_in)) for r in rows if "z" in r]
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
    # the detector's sigma: sqrt(max(std^2, mean, 1)) = sqrt(3.14) here, not std = 1.2
    assert bands[0]["low"] == pytest.approx(3.14 - 3 * 3.14**0.5)
    assert bands[0]["high"] == pytest.approx(3.14 + 3 * 3.14**0.5)
    share = spec(trend_chart(trend(2, [0.1, 0.12], [0.5, 1.0], "share"), mix(id=2)))
    assert not [r for rows in share["datasets"].values() for r in rows if "low" in r]


@pytest.mark.parametrize(
    ("copy", "expected"),
    [(EN, {("Sales", 3), ("Unclassified", 1)}), (ZH, {("業務", 3), ("未分類", 1)})],
)
def test_composition_chart_labels_unclassified(copy, expected):
    counts = [CountOut(key="sales", count=3), CountOut(key=None, count=1)]
    chart = composition_chart(counts, "Role family", copy=copy)
    rows = [r for rows in datasets(chart) for r in rows]
    assert {(r["label"], r["count"]) for r in rows} == expected
    assert "text" in {layer["mark"]["type"] for layer in spec(chart)["layer"]}  # value at tip


@pytest.mark.parametrize(("copy", "fmt"), [(EN, "%b %d"), (ZH, "%m/%d")])
def test_trend_chart_weeks_read_as_dates(copy, fmt):
    chart = spec(trend_chart(trend(1, [2.0, 3.0], [0.5, 1.0]), signal(id=1), copy))
    assert any(
        f"utcFormat(toDate(datum.value), '{fmt}')" == e for e in find_all(chart, "labelExpr")
    )


def test_trend_band_never_collapses_on_a_zero_baseline():
    """A zero baseline (std 0, mean 0) is scored with sigma 1: the band must not be a line."""
    flat = signal(id=1, baseline_mean=0.0, baseline_std=0.0, observed=2.0, z=2.0)
    chart = spec(trend_chart(trend(1, [0.0, 2.0], [None, 2.0]), flat))
    bands = [r for rows in chart["datasets"].values() for r in rows if "low" in r]
    bands = bands or [r for rows in find_all(chart, "values") for r in rows if "low" in r]
    assert (bands[0]["low"], bands[0]["high"]) == (-3.0, 3.0)
