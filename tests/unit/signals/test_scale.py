"""The scoring pipeline must stay fast as postings grow (50k events, all four levels)."""

import random
import time
from datetime import date, timedelta

import pandas as pd

from jobsignal.signals.detectors import mix_shift_scores, volume_scores
from jobsignal.signals.events import COLUMNS
from jobsignal.signals.features import cell_counts
from jobsignal.signals.params import LEVELS, DetectorParams

WEEKS = [date(2026, 6, 1) + timedelta(weeks=i) for i in range(17)]
FAMILIES = [f"family_{i}" for i in range(16)]
COUNTRIES = ["US", "GB", "IE", "DE", "IN", "SG", "CA", "AU", "FR", "ZZ"]


def test_fifty_thousand_events_score_in_under_five_seconds():
    rng = random.Random(7)
    rows = [
        (i, rng.choice(["anthropic", "databricks", "stripe"]), rng.choice(FAMILIES),
         rng.choice(COUNTRIES), rng.choice(WEEKS))
        for i in range(50_000)
    ]  # fmt: skip
    events = pd.DataFrame.from_records(rows, columns=COLUMNS)
    params = DetectorParams()
    available = {c: set(WEEKS) for c in ("anthropic", "databricks", "stripe")}

    start = time.perf_counter()
    company = cell_counts(events, "company", WEEKS[-16:], None)
    total = 0
    for level in LEVELS:
        total += len(volume_scores(cell_counts(events, level, WEEKS, available), params))
        counts = cell_counts(events, level, WEEKS[-16:], None)
        total += len(mix_shift_scores(counts, company, level, params))
    elapsed = time.perf_counter() - start

    assert total > 1_000  # ~3 x 16 x 10 cells at the finest level alone
    assert elapsed < 5.0, f"scoring took {elapsed:.1f}s"
