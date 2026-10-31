import pytest

from jobsignal.extraction.rate_limit import RateLimiter
from tests.unit.extraction.fakes import FakeClock


@pytest.fixture
def clock():
    return FakeClock()


def make_limiter(clock, interval=2.0):
    return RateLimiter(interval, clock=clock, sleep=clock.sleep)


def test_first_request_does_not_wait(clock):
    make_limiter(clock).wait("boards-api.greenhouse.io")
    assert clock.sleeps == []


def test_second_request_waits_remaining_interval(clock):
    limiter = make_limiter(clock)
    limiter.wait("boards-api.greenhouse.io")
    clock.advance(0.5)
    limiter.wait("boards-api.greenhouse.io")
    assert clock.sleeps == [pytest.approx(1.5)]


def test_no_wait_when_interval_already_elapsed(clock):
    limiter = make_limiter(clock)
    limiter.wait("h")
    clock.advance(3.0)
    limiter.wait("h")
    assert clock.sleeps == []


def test_interval_measured_from_end_of_previous_wait(clock):
    limiter = make_limiter(clock)
    limiter.wait("h")
    limiter.wait("h")  # sleeps 2.0
    limiter.wait("h")  # must sleep a full 2.0 again, not 0
    assert clock.sleeps == [pytest.approx(2.0), pytest.approx(2.0)]


def test_hosts_are_limited_independently(clock):
    limiter = make_limiter(clock)
    limiter.wait("a")
    limiter.wait("b")
    assert clock.sleeps == []


def test_zero_interval_never_sleeps(clock):
    limiter = make_limiter(clock, interval=0)
    for _ in range(3):
        limiter.wait("h")
    assert clock.sleeps == []


def test_negative_interval_rejected(clock):
    with pytest.raises(ValueError, match="min_interval"):
        make_limiter(clock, interval=-1)
