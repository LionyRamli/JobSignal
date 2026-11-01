"""Altair chart specs for the dashboard (pure: data in, chart out), in either language.

No colour lives here. Light and dark mode are switched in the browser (Streamlit's ⋮ menu)
without rerunning the script, so colours picked in Python would go stale. Instead:

- text (axes, titles, legends) carries no colour, so Streamlit's chart theme paints it in
  the active mode;
- every mark is coloured through one ordinal scale whose range is ``"category"``, the
  active theme's ``chartCategoricalColors`` (``.streamlit/config.toml``, one palette per
  mode, in ``SLOTS`` order, contrast-tested against that mode's page).

So a theme switch recolours bars, lines, glow and value labels live. Bands are always also
named in words (legend, tooltip, table): colour never carries the meaning alone. No
gridlines and no plot frame: dashed rules mark the real thresholds (±3, ±5). Missing weeks
stay null: Vega-Lite draws a gap.
"""

import math
from collections.abc import Callable, Sequence

import altair as alt
import pandas as pd

from jobsignal.api.schemas import CountOut, SignalOut, SignalTrend
from jobsignal.dashboard.alerts import RED_Z, YELLOW_Z
from jobsignal.dashboard.glossary import EN, Copy

# the theme palette, by position: config.toml lists each mode's colours in this order
SLOTS = ("extreme", "unusual", "below", "series", "ink", "normal")
BAND_ORDER = ("red", "yellow", "none")  # = the first three slots
THRESHOLDS = [-RED_Z, -YELLOW_Z, YELLOW_Z, RED_Z]


def palette(copy: Copy) -> list[str]:
    """The colour scale's domain: bands by their shown names, then the fixed slots."""
    return [copy.band[b] for b in BAND_ORDER] + list(SLOTS[len(BAND_ORDER) :])


def _scale(copy: Copy) -> alt.Scale:
    return alt.Scale(domain=palette(copy), range="category")


def _in_slot(chart: alt.Chart, slot: str, copy: Copy) -> alt.Chart:
    """Colour every mark of ``chart`` with one slot of the active theme's palette."""
    return chart.transform_calculate(slot=f"'{slot}'").encode(
        color=alt.Color("slot:N", scale=_scale(copy), legend=None)
    )


def _week_label(copy: Copy) -> str:
    return f"utcFormat(toDate(datum.value), '{copy.week_axis}')"


def _axis(title: str | None, **extra) -> alt.Axis:
    return alt.Axis(
        title=title, grid=False, domain=False, ticks=False, titleFontWeight="normal",
        labelPadding=6, **extra,
    )  # fmt: skip


def _title(text: str) -> alt.TitleParams:
    return alt.TitleParams(text, anchor="start", fontSize=13, fontWeight="normal")


def _finish(chart):
    """No frame around the plot: the terminal look is marks on the page, nothing else."""
    return chart.configure_view(stroke=None)


def _position(axis: str, field: str):
    return alt.X(field) if axis == "x" else alt.Y(field)


def _threshold_rules(axis: str, copy: Copy) -> alt.Chart:
    """Dashed rules at ±3 (alert) and ±5 (extreme): the lines the bands mean."""
    data = pd.DataFrame(
        {
            axis: [int(t) for t in THRESHOLDS],
            "band": [copy.band["red" if abs(t) >= RED_Z else "yellow"] for t in THRESHOLDS],
        }
    )
    return (
        alt.Chart(data)
        .mark_rule(strokeDash=[4, 4], strokeWidth=1, opacity=0.8)
        .encode(
            _position(axis, f"{axis}:Q"),
            color=alt.Color("band:N", scale=_scale(copy), legend=None),
        )
    )


def _zero_rule(axis: str, copy: Copy) -> alt.Chart:
    data = pd.DataFrame({"zero": [0]})
    rule = alt.Chart(data).mark_rule(opacity=0.6).encode(_position(axis, "zero:Q"))
    return _in_slot(rule, "below", copy)


def z_chart(frame: pd.DataFrame, copy: Copy = EN) -> alt.LayerChart:
    """One bar per alert: its Anomaly Score, coloured by band, signed value at the tip."""
    names = copy.alert_table
    scored = frame[frame["z"].notna()]
    data = pd.DataFrame(
        {
            "alert": [f"#{i} {c} · {cell}" for i, c, cell in
                      zip(scored["id"], scored["company"], scored["cell"], strict=True)],
            "company": scored["company"],
            "where": scored["cell"],
            "signal": [copy.detector.get(d, d) for d in scored["detector"]],
            "trend": [copy.direction.get(d, "—") for d in scored["direction"]],
            "z": scored["z"].astype(float),
            "band": [copy.band[b] for b in scored["band"]],
        }
    )  # fmt: skip
    # a unit of room past the longest bars for their value labels; ±5 always on the axis
    zs = list(data["z"]) or [0.0]
    x_domain = [min(math.floor(min(zs)) - 1, -int(RED_Z) - 1),
                max(math.ceil(max(zs)) + 1, int(RED_Z) + 1)]  # fmt: skip
    base = alt.Chart(data).encode(
        # explicit order: layers with their own transforms cannot merge a data-order sort
        y=alt.Y("alert:N", sort=list(data["alert"]), axis=_axis(None, labelLimit=280)),
        x=alt.X("z:Q", scale=alt.Scale(domain=x_domain), axis=_axis(copy.chart["z_axis"])),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, size=14).encode(
        color=alt.Color(
            "band:N",
            scale=_scale(copy),
            legend=alt.Legend(title=names["band"].label, orient="top", values=palette(copy)[:3]),
        ),
        tooltip=[  # same words as the table's column headings
            alt.Tooltip("company:N", title=names["company"].label),
            alt.Tooltip("where:N", title=names["cell"].label),
            alt.Tooltip("signal:N", title=names["detector"].label),
            alt.Tooltip("trend:N", title=names["direction"].label),
            alt.Tooltip("z:Q", title=names["z"].label, format="+.2f"),
            alt.Tooltip("band:N", title=names["band"].label),
        ],
    )
    text = alt.Text("z:Q", format="+.1f")
    right = base.transform_filter("datum.z >= 0").mark_text(align="left", dx=5)
    left = base.transform_filter("datum.z < 0").mark_text(align="right", dx=-5)
    return _finish(
        alt.layer(
            _zero_rule("x", copy), _threshold_rules("x", copy), bars,
            _in_slot(right.encode(text=text), "ink", copy),
            _in_slot(left.encode(text=text), "ink", copy),
        ).resolve_scale(color="independent")  # else the legend-less layers hide the legend
    )  # fmt: skip


def _glowing_line(
    data: alt.Data, x: alt.X, field: str, title: str, fmt: str, copy: Copy
) -> alt.LayerChart:
    """A crisp 2px line over a wide, faint copy of itself: the terminal 'glow'.

    Both wear the theme's series colour, so the glow follows light/dark mode too.
    """
    y = alt.Y(f"{field}:Q", axis=_axis(title))
    glow = alt.Chart(data).mark_line(strokeWidth=8, opacity=0.18).encode(x=x, y=y)
    line = (
        alt.Chart(data)
        .mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=64, filled=True))
        .encode(
            x=x,
            y=y,
            tooltip=[
                alt.Tooltip("week:O", title=copy.alert_table["week"].label),
                alt.Tooltip(f"{field}:Q", title=title, format=fmt),
            ],
        )
    )
    return alt.layer(_in_slot(glow, "series", copy), _in_slot(line, "series", copy))


def trend_chart(trend: SignalTrend, signal: SignalOut, copy: Copy = EN) -> alt.VConcatChart:
    """Top: the weekly value (volume: over its normal range). Bottom: the Anomaly Score."""
    words = copy.chart
    # inline records, not a DataFrame: pandas/Altair would turn None into NaN, but a
    # missing week must reach Vega-Lite as null so the line breaks instead of dipping
    rows = [{"week": p.week_start.isoformat(), "value": p.value, "z": p.z} for p in trend.points]
    values = alt.Data(values=[{"week": r["week"], "value": r["value"]} for r in rows])
    zs = alt.Data(values=[{"week": r["week"], "z": r["z"]} for r in rows])
    share = trend.metric == "share"
    value_title = words["value_share"] if share else words["value_volume"]
    x = alt.X("week:O", axis=_axis(None, labelAngle=0, labelExpr=_week_label(copy)))
    top = _glowing_line(values, x, "value", value_title, ".1%" if share else ".3~f", copy)
    heading = value_title + (words["in_slice"] if share else "")
    if not share and signal.baseline_mean is not None and signal.baseline_std is not None:
        # the detector's own sigma (Poisson floor), so the band explains the score shown
        sigma = math.sqrt(max(signal.baseline_std**2, signal.baseline_mean, 1.0))
        band = pd.DataFrame(
            {
                "low": [signal.baseline_mean - 3 * sigma],
                "high": [signal.baseline_mean + 3 * sigma],
            }
        )
        normal = (
            alt.Chart(band)
            .mark_rect(opacity=0.9)
            .encode(
                y="low:Q",
                y2="high:Q",
                tooltip=[
                    alt.Tooltip("low:Q", title=words["normal_from"], format=".1f"),
                    alt.Tooltip("high:Q", title=words["normal_to"], format=".1f"),
                ],
            )
        )
        top = alt.layer(_in_slot(normal, "normal", copy), top)
        heading += words["normal_band"]
    bottom = alt.layer(
        _zero_rule("y", copy),
        _threshold_rules("y", copy),
        _glowing_line(zs, x, "z", copy.alert_table["z"].label, "+.2f", copy),
    )
    return _finish(
        alt.vconcat(
            top.properties(height=170, title=_title(heading)),
            bottom.properties(height=170, title=_title(words["score_title"])),
        )
    )


def composition_chart(
    counts: Sequence[CountOut],
    dimension: str,
    name: Callable[[str], str] | None = None,
    copy: Copy = EN,
) -> alt.LayerChart:
    """Open postings per category (server-side counts), value at each bar's tip."""
    name = name or copy.pretty
    words = copy.chart
    data = pd.DataFrame(
        {
            "label": [name(c.key) if c.key else words["unclassified"] for c in counts],
            "count": [c.count for c in counts],
        }
    )
    order = data.sort_values("count", ascending=False, kind="stable")["label"].tolist()
    base = alt.Chart(data).encode(
        y=alt.Y("label:N", sort=order, axis=_axis(None, labelLimit=180)),  # biggest first
        x=alt.X("count:Q", axis=None),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, size=14).encode(
        tooltip=[
            alt.Tooltip("label:N", title=dimension),
            alt.Tooltip("count:Q", title=words["open_roles"]),
        ],
    )
    tips = base.mark_text(align="left", dx=5).encode(text="count:Q")
    title = _title(words["composition_title"].format(dimension=dimension))
    layers = alt.layer(_in_slot(bars, "series", copy), _in_slot(tips, "ink", copy))
    return _finish(layers.properties(title=title))
