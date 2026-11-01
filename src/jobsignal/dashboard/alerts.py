"""Alert logic for the dashboard: colour bands, grouping, plain-English copy, freshness.

Pure functions over the API's response models: no Streamlit, no I/O.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from jobsignal.api.schemas import SignalOut, SignalTrend
from jobsignal.dashboard.trends import (  # noqa: F401 - stale_* re-exported
    STALE_AFTER,
    delta_prev,
    delta_vs_baseline,
    sparkline,
    stale_companies,
)

YELLOW_Z = 3.0
RED_Z = 5.0
LEVELS_ORDER = ("company", "company_family", "company_country", "company_family_country")
ALERT_COLUMNS = [
    "id", "band", "company", "cell", "detector", "direction", "z", "dz_prev_week",
    "observed", "baseline", "d_baseline", "trend", "week", "provisional", "also_at",
]  # fmt: skip

Band = Literal["red", "yellow", "none"]


def z_band(z: float | None) -> Band:
    """User rule: red when |z| > 5, yellow when 3 <= |z| <= 5, otherwise none."""
    if z is None:
        return "none"
    if abs(z) > RED_Z:
        return "red"
    if abs(z) >= YELLOW_Z:
        return "yellow"
    return "none"


def cell_label(s: SignalOut) -> str:
    return f"{s.role_family or 'all roles'} · {s.country_code or 'all countries'}"


def describe(s: SignalOut) -> str:
    """One plain-English sentence explaining a score."""
    prefix = f"{s.company} · {cell_label(s)}"
    if s.z is None:
        return f"{prefix}: not scored ({s.status})"
    if s.detector == "mix_shift":
        recent = "n/a" if s.share_recent is None else f"{s.share_recent:.1%}"
        baseline = "n/a" if s.share_baseline is None else f"{s.share_baseline:.1%}"
        return (
            f"{prefix}: {recent} of recent postings vs {baseline} in the baseline "
            f"(z = {s.z:+.2f}, provisional)"
        )
    observed = "n/a" if s.observed is None else f"{s.observed:g}"
    mean = "n/a" if s.baseline_mean is None else f"{s.baseline_mean:.1f}"
    std = "n/a" if s.baseline_std is None else f"{s.baseline_std:.1f}"
    return (
        f"{prefix}: {observed} new postings in the week of {s.week_start.isoformat()} "
        f"vs a baseline of {mean} ± {std} (z = {s.z:+.2f})"
    )


@dataclass(frozen=True)
class AlertGroup:
    headline: SignalOut
    related: tuple[SignalOut, ...]


def _specificity(s: SignalOut) -> int:
    return LEVELS_ORDER.index(s.level) if s.level in LEVELS_ORDER else -1


def group_alerts(signals: Sequence[SignalOut]) -> list[AlertGroup]:
    """One group per (company, detector, week, direction): the levels of one event.

    Headline = largest |z|; ties go to the more specific level, then the lower id. Rows
    without a z are singleton groups, listed last.
    """
    buckets: dict[tuple, list[SignalOut]] = {}
    unscored: list[SignalOut] = []
    for s in signals:
        if s.z is None:
            unscored.append(s)
            continue
        buckets.setdefault((s.company, s.detector, s.week_start, s.direction), []).append(s)
    groups = []
    for members in buckets.values():
        ranked = sorted(members, key=lambda s: (-abs(s.z), -_specificity(s), s.id))
        groups.append(AlertGroup(ranked[0], tuple(ranked[1:])))
    groups.sort(key=lambda g: (-abs(g.headline.z), g.headline.id))
    groups += [AlertGroup(s, ()) for s in sorted(unscored, key=lambda s: s.id)]
    return groups


def safe_url(url: str | None) -> str | None:
    """The URL only if it is http(s): scraped links must never run script."""
    if not url:
        return None
    return url if url.strip().lower().startswith(("http://", "https://")) else None


def alerts_frame(groups: Sequence[AlertGroup], trends: Mapping[int, SignalTrend]) -> pd.DataFrame:
    rows = []
    for group in groups:
        s = group.headline
        trend = trends.get(s.id)
        mix = s.detector == "mix_shift"
        rows.append(
            {
                "id": s.id,
                "band": z_band(s.z),
                "company": s.company,
                "cell": cell_label(s),
                "detector": s.detector,
                "direction": s.direction,
                "z": s.z,
                "dz_prev_week": delta_prev([p.z for p in trend.points]) if trend else None,
                "observed": s.share_recent if mix else s.observed,
                "baseline": s.share_baseline if mix else s.baseline_mean,
                "d_baseline": delta_vs_baseline(s),
                "trend": sparkline(trend) if trend else [],
                "week": s.week_start,
                "provisional": s.provisional,
                "also_at": ", ".join(cell_label(r) for r in group.related),
            }
        )
    return pd.DataFrame(rows, columns=ALERT_COLUMNS, dtype=object)
