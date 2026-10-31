"""Detector maths on synthetic series; expected values are hand-computed in each docstring."""

import math
import random
from datetime import date, timedelta

import pandas as pd
import pytest

from jobsignal.signals.detectors import SCORE_COLUMNS, mix_shift_scores, volume_scores
from jobsignal.signals.events import COLUMNS
from jobsignal.signals.features import cell_counts
from jobsignal.signals.params import DetectorParams

P = DetectorParams()
START = date(2026, 6, 1)  # a Monday


def weeks(n):
    return [START + timedelta(weeks=i) for i in range(n)]


def series_counts(values, level="company_family_country", cell=("acme", "sales", "US")):
    """values: one per week; None marks a missing (outage) week."""
    ws = weeks(len(values))
    rows, pid = [], 0
    for week, n in zip(ws, values, strict=True):
        for _ in range(n or 0):
            pid += 1
            rows.append((pid, *cell, week) if len(cell) == 3 else (pid, cell[0], "x", "US", week))
    events = pd.DataFrame.from_records(rows, columns=COLUMNS)
    available = {cell[0]: {w for w, v in zip(ws, values, strict=True) if v is not None}}
    return cell_counts(events, level, ws, available)


def only_row(frame):
    assert len(frame) == 1, frame
    return frame.iloc[0]


def test_output_columns():
    out = volume_scores(series_counts([1] * 9), P)
    assert list(out.columns) == SCORE_COLUMNS


def test_volume_z_matches_hand_computation():
    """baseline [4,6,5,5,4,6,5,5]: mu=5, s^2=4/7=0.571; sigma_eff=sqrt(max(.571,5,1))=2.236;
    x=12 -> z=7/2.236=3.130 -> expansion, notable."""
    row = only_row(volume_scores(series_counts([4, 6, 5, 5, 4, 6, 5, 5, 12]), P))
    assert row["z"] == pytest.approx(3.1305, abs=1e-3)
    assert (row["observed"], row["baseline_mean"], row["baseline_weeks"]) == (12, 5, 8)
    assert row["baseline_std"] == pytest.approx(math.sqrt(4 / 7))
    assert (row["status"], row["is_signal"], row["direction"], row["severity"]) == (
        "scored", True, "expansion", "notable",
    )  # fmt: skip
    assert row["week_start"] == START + timedelta(weeks=8)


def test_zero_variance_baseline_is_finite():
    """[0]*8 -> 6: sigma_eff = sqrt(max(0,0,1)) = 1 -> z = 6.0 -> strong expansion."""
    row = only_row(volume_scores(series_counts([0] * 8 + [6]), P))
    assert row["z"] == pytest.approx(6.0)
    assert (row["is_signal"], row["severity"]) == (True, "strong")


def test_single_posting_is_never_a_signal():
    """[0]*8 -> 1: z = 1.0 but the cell is too small for either direction; raw z is kept."""
    row = only_row(volume_scores(series_counts([0] * 8 + [1]), P))
    assert row["status"] == "below_min_count"
    assert row["z"] == pytest.approx(1.0)
    assert not row["is_signal"]
    assert row["direction"] is None


def test_insufficient_history():
    row = only_row(volume_scores(series_counts([3, 3, 3, 3, 3, 9]), P))
    assert row["status"] == "insufficient_history"
    assert row["z"] is None
    assert row["baseline_weeks"] == 5


def test_missing_weeks_excluded_from_baseline():
    """10 weeks with 2 outages: the baseline is the 8 AVAILABLE weeks before the target."""
    values = [5, None, 5, 5, None, 5, 5, 5, 5, 5, 20]
    row = only_row(volume_scores(series_counts(values), P))
    assert (row["baseline_weeks"], row["baseline_mean"]) == (8, 5)
    # the outage zeros did not drag the mean down; sigma_eff = sqrt(5) -> z = 15/2.236
    assert row["z"] == pytest.approx(15 / math.sqrt(5))


def test_missing_target_week_gives_no_row():
    assert volume_scores(series_counts([5] * 8 + [None]), P).empty


def test_contraction_flagged():
    """[12]*8 -> 0: mu=12, sigma_eff=sqrt(12)=3.464, z=-3.464 -> contraction, notable.
    [20]*8 -> 0: z=-20/4.472=-4.47 -> strong."""
    row = only_row(volume_scores(series_counts([12] * 8 + [0]), P))
    assert row["z"] == pytest.approx(-12 / math.sqrt(12))
    assert (row["status"], row["is_signal"], row["direction"], row["severity"]) == (
        "scored", True, "contraction", "notable",
    )  # fmt: skip
    strong = only_row(volume_scores(series_counts([20] * 8 + [0]), P))
    assert (strong["direction"], strong["severity"]) == ("contraction", "strong")


def test_tiny_cells_cannot_fake_a_freeze():
    """[1]*8 -> 0: z = -1/1 = -1 (no). [4]*8 -> 0: z = -2 and mu < 5 (no)."""
    for baseline in (1, 4):
        row = only_row(volume_scores(series_counts([baseline] * 8 + [0]), P))
        assert not row["is_signal"], baseline


def test_raw_values_kept_for_non_signals():
    row = only_row(volume_scores(series_counts([5] * 8 + [6]), P))
    assert (row["status"], row["is_signal"]) == ("scored", False)
    assert math.isfinite(row["z"])
    assert (row["observed"], row["baseline_mean"]) == (6, 5)


def share_counts(cells, n_weeks=16):
    """cells: {(company, family): (recent_total, baseline_total)} spread evenly over weeks."""
    ws = weeks(n_weeks)
    recent, baseline = ws[-P.recent_weeks :], ws[: P.mix_baseline_weeks]
    rows, pid = [], 0
    for (company, family), (n_recent, n_base) in cells.items():
        for total, window in ((n_recent, recent), (n_base, baseline)):
            for i in range(total):
                pid += 1
                rows.append((pid, company, family, "US", window[i % len(window)]))
    events = pd.DataFrame.from_records(rows, columns=COLUMNS)
    return (
        cell_counts(events, "company_family", ws, None),
        cell_counts(events, "company", ws, None),
    )


def mix_row(frame, family):
    return only_row(frame[frame["role_family"] == family])


def test_mix_shift_matches_hand_computation():
    """n_r=15/N_r=50 (0.30) vs n_b=10/N_b=150 (0.0667); p=25/200=0.125;
    z = 0.2333 / sqrt(0.125*0.875*(1/50+1/150)) = 4.32 -> strong expansion."""
    counts, company = share_counts({("acme", "sales"): (15, 10), ("acme", "eng"): (35, 140)})
    row = mix_row(mix_shift_scores(counts, company, "company_family", P), "sales")
    assert row["z"] == pytest.approx(4.3205, abs=1e-3)
    assert (row["observed"], row["baseline_mean"]) == (15, 10)
    assert (row["is_signal"], row["direction"], row["severity"]) == (True, "expansion", "strong")


def test_mix_shift_contraction():
    """n_r=2/100 (0.02) vs n_b=30/150 (0.20); p=32/250=0.128 -> z = -4.17 -> contraction."""
    counts, company = share_counts({("acme", "sales"): (2, 30), ("acme", "eng"): (98, 120)})
    row = mix_row(mix_shift_scores(counts, company, "company_family", P), "sales")
    assert row["z"] == pytest.approx(-4.17, abs=1e-2)
    assert (row["is_signal"], row["direction"]) == (True, "contraction")


def test_uniform_growth_is_not_a_mix_shift():
    """Survivorship ramp: every cell x4 in the recent window -> shares unchanged -> z = 0."""
    cells = {("acme", f): (4 * n, n * 3) for f, n in [("sales", 10), ("eng", 20), ("data", 6)]}
    counts, company = share_counts(cells)
    out = mix_shift_scores(counts, company, "company_family", P)
    assert not out["is_signal"].any()
    assert out["z"].abs().max() < 0.5


def test_mix_shift_needs_company_baseline():
    counts, company = share_counts({("acme", "sales"): (10, 5), ("acme", "eng"): (10, 15)})
    out = mix_shift_scores(counts, company, "company_family", P)  # N_b = 20 < 30
    assert set(out["status"]) == {"insufficient_history"}
    assert out["z"].isna().all()


def test_mix_shift_not_defined_for_company_level():
    _counts, company = share_counts({("acme", "sales"): (10, 40)})
    assert mix_shift_scores(company, company, "company", P).empty


def test_no_inf_or_nan_anywhere():
    rng = random.Random(42)
    for _ in range(500):
        values = [rng.choice([None, 0, 0, 1, 2, 3, 7]) for _ in range(rng.randint(1, 12))]
        for z in volume_scores(series_counts(values), P)["z"]:
            assert z is None or math.isfinite(z), values
    for _ in range(200):
        cells = {("acme", f): (rng.randint(0, 6), rng.randint(0, 40)) for f in ("a", "b", "c")}
        counts, company = share_counts(cells)
        for z in mix_shift_scores(counts, company, "company_family", P)["z"]:
            assert z is None or math.isfinite(z), cells


def test_expansion_needs_min_count_even_with_high_z():
    """[0]*8 -> 4: z = 4.0 (strong!) but only 4 openings < volume_min_count -> no signal."""
    row = only_row(volume_scores(series_counts([0] * 8 + [4]), P))
    assert row["z"] == pytest.approx(4.0)
    assert not row["is_signal"]


def test_contraction_needs_min_baseline_with_looser_threshold():
    """With contraction_z_threshold=-1.5, [4]*8 -> 0 gives z = -2 <= -1.5, but mu = 4 < 5."""
    loose = DetectorParams(contraction_z_threshold=-1.5)
    row = only_row(volume_scores(series_counts([4] * 8 + [0]), loose))
    assert row["z"] == pytest.approx(-2.0)
    assert not row["is_signal"]
    assert only_row(volume_scores(series_counts([6] * 8 + [0]), loose))["is_signal"]


def test_mix_expansion_needs_min_recent_count():
    """n_r=4/10 (0.40) vs n_b=5/200 (0.025): z is large, but only 4 recent openings."""
    counts, company = share_counts({("acme", "sales"): (4, 5), ("acme", "eng"): (6, 195)})
    row = mix_row(mix_shift_scores(counts, company, "company_family", P), "sales")
    assert row["z"] > P.z_threshold
    assert row["status"] == "scored"
    assert not row["is_signal"]


def test_mix_contraction_needs_min_baseline_count():
    """n_r=5/1000 (0.005) vs n_b=4/30 (0.133): z = -7.4, but only 4 baseline openings."""
    counts, company = share_counts({("acme", "sales"): (5, 4), ("acme", "eng"): (995, 26)})
    row = mix_row(mix_shift_scores(counts, company, "company_family", P), "sales")
    assert row["z"] < P.contraction_z_threshold
    assert row["status"] == "scored"
    assert not row["is_signal"]
