"""Altair chart specs for the dashboard (pure: data in, chart out).

Band colours come from the reference status palette (critical / warning) plus a neutral
gray for "no band"; the band is always also shown as text (legend, tooltip, table column),
so colour never carries the meaning alone. Missing weeks stay null: Vega-Lite draws a gap.
"""

from collections.abc import Sequence

import altair as alt
import pandas as pd

from jobsignal.api.schemas import CountOut, SignalOut, SignalTrend
from jobsignal.dashboard.alerts import RED_Z, YELLOW_Z

BAND_DOMAIN = ["red", "yellow", "none"]
BAND_COLORS = ["#d03b3b", "#fab219", "#8f8e86"]
RULE_COLOR = "#c3c2b7"
LINE_COLOR = "#2a78d3"
BASELINE_FILL = "#e1e0d9"
THRESHOLDS = [-RED_Z, -YELLOW_Z, YELLOW_Z, RED_Z]


def _rules(axis: str) -> alt.Chart:
    data = pd.DataFrame({axis: [int(t) for t in THRESHOLDS]})
    return (
        alt.Chart(data)
        .mark_rule(strokeDash=[4, 4], color=RULE_COLOR)
        .encode(**{axis: alt.X(f"{axis}:Q") if axis == "x" else alt.Y(f"{axis}:Q")})
    )


def z_chart(frame: pd.DataFrame) -> alt.LayerChart:
    """Horizontal bars of each alert's z, coloured by band, with dashed rules at ±3 and ±5."""
    scored = frame[frame["z"].notna()]
    data = pd.DataFrame(
        {
            "alert": [f"#{i} {c} · {cell}" for i, c, cell in
                      zip(scored["id"], scored["company"], scored["cell"], strict=True)],
            "z": scored["z"].astype(float),
            "band": scored["band"],
            "direction": scored["direction"],
        }
    )  # fmt: skip
    bars = (
        alt.Chart(data)
        .mark_bar(cornerRadiusEnd=4, size=14)
        .encode(
            x=alt.X("z:Q", title="z-score"),
            y=alt.Y("alert:N", sort=None, title=None),
            color=alt.Color(
                "band:N",
                scale=alt.Scale(domain=BAND_DOMAIN, range=BAND_COLORS),
                legend=alt.Legend(title="Band"),
            ),
            tooltip=["alert:N", alt.Tooltip("z:Q", format="+.2f"), "band:N", "direction:N"],
        )
    )
    return alt.layer(bars, _rules("x"))


def trend_chart(trend: SignalTrend, signal: SignalOut) -> alt.VConcatChart:
    """Top: the weekly value (volume: with a baseline mean +/- 3 std band). Bottom: z."""
    # inline records, not a DataFrame: pandas/Altair would turn None into NaN, but a
    # missing week must reach Vega-Lite as null so the line breaks instead of dipping
    rows = [{"week": p.week_start.isoformat(), "value": p.value, "z": p.z} for p in trend.points]
    values = alt.Data(values=[{"week": r["week"], "value": r["value"]} for r in rows])
    zs = alt.Data(values=[{"week": r["week"], "z": r["z"]} for r in rows])
    value_title = "share of company openings" if trend.metric == "share" else "new postings"
    value_line = (
        alt.Chart(values)
        .mark_line(point=alt.OverlayMarkDef(size=64), strokeWidth=2, color=LINE_COLOR)
        .encode(
            x=alt.X("week:O", title="week"),
            y=alt.Y("value:Q", title=value_title),
            tooltip=["week:O", alt.Tooltip("value:Q", format=".3~f")],
        )
    )
    top = value_line
    if (
        trend.metric == "count"
        and signal.baseline_mean is not None
        and signal.baseline_std is not None
    ):
        band = pd.DataFrame(
            {
                "low": [signal.baseline_mean - 3 * signal.baseline_std],
                "high": [signal.baseline_mean + 3 * signal.baseline_std],
            }
        )
        baseline = (
            alt.Chart(band)
            .mark_rect(color=BASELINE_FILL, opacity=0.6)
            .encode(y="low:Q", y2="high:Q")
        )
        top = alt.layer(baseline, value_line)
    z_line = (
        alt.Chart(zs)
        .mark_line(point=alt.OverlayMarkDef(size=64), strokeWidth=2, color=LINE_COLOR)
        .encode(
            x=alt.X("week:O", title="week"),
            y=alt.Y("z:Q", title="z-score"),
            tooltip=["week:O", alt.Tooltip("z:Q", format="+.2f")],
        )
    )
    bottom = alt.layer(z_line, _rules("y"))
    return alt.vconcat(top.properties(height=160), bottom.properties(height=160))


def composition_chart(counts: Sequence[CountOut], title: str) -> alt.Chart:
    """Open postings per category (server-side counts); a null key reads 'unclassified'."""
    data = pd.DataFrame(
        {"label": [c.key or "unclassified" for c in counts], "count": [c.count for c in counts]}
    )
    return (
        alt.Chart(data, title=title)
        .mark_bar(cornerRadiusEnd=4, size=14, color=LINE_COLOR)
        .encode(
            x=alt.X("count:Q", title="open postings"),
            y=alt.Y("label:N", sort="-x", title=None),
            tooltip=["label:N", "count:Q"],
        )
    )
