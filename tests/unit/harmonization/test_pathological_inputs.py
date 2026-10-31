"""Untrusted ATS strings must not make the classifiers slow or crash (ReDoS / blow-up)."""

import time

import pytest

from jobsignal.harmonization.locations import parse_locations
from jobsignal.harmonization.roles import classify_title

HUGE_TITLE = "Senior Staff Software Engineer, " * 320  # ~10,000 chars
HUGE_LOCATION = "; ".join(["San Francisco, CA", "Remote - Texas", "Atlantis"] * 600)
NASTY = [
    "-" * 10_000,
    "us-" * 3_000 + "remote",
    "us-" * 1_300 + "remote",  # under the length cap: deep prefix recursion
    "remote " * 2_000,
    ", " * 5_000,
    "(" * 5_000 + ")" * 5_000,
    "a-" * 5_000,
]


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return result, time.perf_counter() - start


def test_huge_title_is_fast():
    classify_title("warm up")
    result, seconds = timed(classify_title, HUGE_TITLE, "Engineering")
    assert seconds < 1.0
    assert result.family.value == "software_engineering"


def test_huge_location_list_is_fast_and_deduplicated():
    parse_locations("warm up")
    result, seconds = timed(parse_locations, HUGE_LOCATION)
    assert seconds < 1.0
    assert [loc.key for loc in result.locations] == [
        "city|US|US-CA|San Francisco",
        "remote|US|US-TX|",
    ]
    assert result.unresolved == ("Atlantis",)


@pytest.mark.parametrize("raw", NASTY, ids=range(len(NASTY)))
def test_adversarial_location_strings_are_fast(raw):
    _, seconds = timed(parse_locations, raw)
    assert seconds < 1.0


@pytest.mark.parametrize("raw", NASTY, ids=range(len(NASTY)))
def test_adversarial_titles_are_fast(raw):
    _, seconds = timed(classify_title, raw, raw)
    assert seconds < 1.0
