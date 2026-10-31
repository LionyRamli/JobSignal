"""Accuracy gate on hand-labelled real titles (see tests/fixtures/harmonization/README.md)."""

import csv

import pytest

from jobsignal.harmonization.roles import classify_title
from tests.conftest import PROJECT_ROOT

GOLDEN = PROJECT_ROOT / "tests" / "fixtures" / "harmonization" / "golden_titles.csv"
THRESHOLD = 0.90


def rows(split):
    with GOLDEN.open(encoding="utf-8", newline="") as handle:
        return [r for r in csv.DictReader(handle) if r["split"] == split]


def test_golden_file_shape():
    tune, holdout = rows("tune"), rows("holdout")
    assert len(tune) + len(holdout) == 201
    assert len(holdout) == 50


@pytest.mark.parametrize("split", ["tune", "holdout"])
@pytest.mark.parametrize("field", ["family", "seniority"])
def test_golden_titles_meet_thresholds(split, field):
    data = rows(split)
    misses = []
    for row in data:
        result = classify_title(row["title"], row["department"] or None)
        got = getattr(result, field).value
        if got != row[field]:
            misses.append(f"{row['title']!r} [{row['department']}]: {got} != {row[field]}")
    accuracy = 1 - len(misses) / len(data)
    assert accuracy >= THRESHOLD, (
        f"{field} accuracy on {split} = {accuracy:.1%} < {THRESHOLD:.0%}\n" + "\n".join(misses)
    )
