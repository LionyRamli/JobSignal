"""Hiring-anomaly detectors over weekly cell counts (see the Phase 1.4 spec for the maths).

volume:    the target (newest) week of each cell against the previous ``baseline_weeks``
           AVAILABLE weeks: sigma_eff = sqrt(max(s^2, mu, 1)), z = (x - mu) / sigma_eff.
mix_shift: a cell's share of its company's openings in the last ``recent_weeks`` against the
           ``mix_baseline_weeks`` before (two-proportion z). Provisional: published-date data.

Both flag expansions (z >= z_threshold) and contractions (z <= contraction_z_threshold) and
keep the raw z and inputs on every row so consumers can apply their own colour bands.
"""

import math
from typing import Any

import pandas as pd

from jobsignal.signals.params import DetectorParams

SCORE_COLUMNS = [
    "detector",
    "company",
    "role_family",
    "country",
    "week_start",
    "observed",
    "baseline_mean",
    "baseline_std",
    "baseline_weeks",
    "z",
    "status",
    "is_signal",
    "direction",
    "severity",
]
_NULLABLE = (
    "baseline_mean",
    "baseline_std",
    "z",
    "direction",
    "severity",
    "role_family",
    "country",
)


def _frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(records, columns=SCORE_COLUMNS)
    for column in _NULLABLE:  # keep real None (not NaN) for NULL-able outputs
        frame[column] = pd.Series([r[column] for r in records], dtype=object)
    return frame


def _cell_keys(index_names: list[str], cell: Any) -> dict[str, Any]:
    keys = index_names[:-1]  # last level is "week"
    values = cell if isinstance(cell, tuple) else (cell,)
    found = dict(zip(keys, values, strict=True))
    return {
        "company": found["company"],
        "role_family": found.get("role_family"),
        "country": found.get("country"),
    }


def _verdict(
    z: float | None, expansion_ok: bool, contraction_ok: bool, params: DetectorParams
) -> tuple[bool, str | None, str | None]:
    if z is None:
        return False, None, None
    if z >= params.z_threshold and expansion_ok:
        direction = "expansion"
    elif z <= params.contraction_z_threshold and contraction_ok:
        direction = "contraction"
    else:
        return False, None, None
    severity = "strong" if abs(z) >= params.strong_z else "notable"
    return True, direction, severity


def volume_scores(counts: pd.DataFrame, params: DetectorParams) -> pd.DataFrame:
    """One row per cell whose target (newest) week is available."""
    if counts.empty:
        return _frame([])
    names = list(counts.index.names)
    keys = names[:-1]
    target = max(counts.index.get_level_values("week"))
    records = []
    for cell, group in counts.groupby(level=keys if len(keys) > 1 else keys[0]):
        group = group.droplevel(keys).sort_index()
        if target not in group.index or not group.loc[target, "available"]:
            continue
        x = float(group.loc[target, "count"])
        prior = group[(group.index < target) & group["available"]]["count"].tail(
            params.baseline_weeks
        )
        n = len(prior)
        record = {"detector": "volume", **_cell_keys(names, cell), "week_start": target}
        record.update(observed=x, baseline_weeks=n, baseline_std=None, z=None)
        record["baseline_mean"] = float(prior.mean()) if n else None
        if n < params.baseline_weeks:
            record.update(status="insufficient_history", is_signal=False)
            record.update(direction=None, severity=None)
            records.append(record)
            continue
        mu = float(prior.mean())
        s = float(prior.std(ddof=1))
        sigma = math.sqrt(max(s * s, mu, 1.0))  # Poisson floor: never divide by ~0
        z = (x - mu) / sigma
        too_small = x < params.volume_min_count and mu < params.contraction_min_baseline
        is_signal, direction, severity = _verdict(
            z,
            expansion_ok=x >= params.volume_min_count,
            contraction_ok=mu >= params.contraction_min_baseline,
            params=params,
        )
        record.update(
            baseline_std=s,
            z=z,
            status="below_min_count" if too_small else "scored",  # label only
            is_signal=is_signal,
            direction=direction,
            severity=severity,
        )
        records.append(record)
    return _frame(records)


def mix_shift_scores(
    counts: pd.DataFrame, company_counts: pd.DataFrame, level: str, params: DetectorParams
) -> pd.DataFrame:
    """Share-shift per cell: last ``recent_weeks`` vs the ``mix_baseline_weeks`` before them.

    ``company_counts`` is the company-level cell_counts output: company totals must count each
    posting once, even when a cell level (e.g. country) counts it in several cells.
    """
    if level == "company" or counts.empty:
        return _frame([])
    names = list(counts.index.names)
    keys = names[:-1]
    all_weeks = sorted(set(counts.index.get_level_values("week")))
    recent = all_weeks[-params.recent_weeks :]
    baseline = all_weeks[-(params.recent_weeks + params.mix_baseline_weeks) : -params.recent_weeks]

    totals = company_counts["count"].fillna(0)
    company_week = totals.index.get_level_values("week")
    by_company_recent = totals[company_week.isin(recent)].groupby(level="company").sum()
    by_company_base = totals[company_week.isin(baseline)].groupby(level="company").sum()

    records = []
    for cell, group in counts.groupby(level=keys if len(keys) > 1 else keys[0]):
        group = group.droplevel(keys)["count"].fillna(0)
        n_r = float(group[group.index.isin(recent)].sum())
        n_b = float(group[group.index.isin(baseline)].sum())
        cell_keys = _cell_keys(names, cell)
        big_r = float(by_company_recent.get(cell_keys["company"], 0.0))
        big_b = float(by_company_base.get(cell_keys["company"], 0.0))
        record = {"detector": "mix_shift", **cell_keys, "week_start": recent[-1]}
        record.update(observed=n_r, baseline_mean=n_b, baseline_std=None)
        record["baseline_weeks"] = len(baseline)
        if big_b < params.mix_min_company_baseline or big_r == 0:
            record.update(z=None, status="insufficient_history", is_signal=False)
            record.update(direction=None, severity=None)
            records.append(record)
            continue
        p = (n_r + n_b) / (big_r + big_b)
        denominator = math.sqrt(p * (1 - p) * (1 / big_r + 1 / big_b))
        z = 0.0 if denominator == 0 else (n_r / big_r - n_b / big_b) / denominator
        too_small = n_r < params.mix_min_recent and n_b < params.mix_min_recent
        is_signal, direction, severity = _verdict(
            z,
            expansion_ok=n_r >= params.mix_min_recent,
            contraction_ok=n_b >= params.mix_min_recent,
            params=params,
        )
        record.update(
            z=z,
            status="below_min_count" if too_small else "scored",  # label only
            is_signal=is_signal,
            direction=direction,
            severity=severity,
        )
        records.append(record)
    return _frame(records)
