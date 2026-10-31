"""Accuracy gate on the 150 most frequent real location pieces (91% of volume)."""

import csv

import pytest

from jobsignal.harmonization.locations import parse_locations
from tests.conftest import PROJECT_ROOT

GOLDEN = PROJECT_ROOT / "tests" / "fixtures" / "harmonization" / "golden_locations.csv"
THRESHOLD = 0.95


def rows(split):
    with GOLDEN.open(encoding="utf-8", newline="") as handle:
        return [r for r in csv.DictReader(handle) if r["split"] == split]


def test_golden_file_shape():
    assert len(rows("tune")) + len(rows("holdout")) == 150


@pytest.mark.parametrize("split", ["tune", "holdout"])
def test_golden_locations_meet_threshold(split):
    data = rows(split)
    misses = []
    for row in data:
        expected = [k for k in row["expected"].split(";") if k]
        got = [loc.key for loc in parse_locations(row["piece"]).locations]
        if got != expected:
            misses.append(f"{row['piece']!r}: {got} != {expected}")
    accuracy = 1 - len(misses) / len(data)
    assert accuracy >= THRESHOLD, (
        f"location accuracy on {split} = {accuracy:.1%} < {THRESHOLD:.0%}\n" + "\n".join(misses)
    )
