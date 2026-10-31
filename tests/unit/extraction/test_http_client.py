import logging

import httpx
import pytest

from jobsignal.extraction.errors import (
    ExtractionError,
    InvalidPayloadError,
    ResponseTooLargeError,
    RetryExhaustedError,
    SourceNotFoundError,
)
from jobsignal.extraction.http_client import RETRYABLE_STATUSES, USER_AGENT, HttpClient
from jobsignal.extraction.rate_limit import RateLimiter

URL = "https://boards-api.greenhouse.io/v1/boards/anthropic/departments"
OK = {"departments": []}


class Scripted:
    """MockTransport handler that replays responses (or raises exceptions) in order."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class SpyLimiter(RateLimiter):
    def __init__(self):
        super().__init__(0)
        self.waits: list[str] = []

    def wait(self, host):
        self.waits.append(host)


def ok(payload=OK):
    return httpx.Response(200, json=payload)


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def make_client(sleeps):
    def factory(handler, **kwargs):
        kwargs.setdefault("rate_limiter", RateLimiter(0))
        return HttpClient(
            transport=httpx.MockTransport(handler),
            sleep=sleeps.append,
            rand=lambda: 1.0,
            **kwargs,
        )

    return factory


def test_retryable_statuses_are_exactly_429_and_5xx_gateway_errors():
    assert frozenset({429, 500, 502, 503, 504}) == RETRYABLE_STATUSES


def test_returns_parsed_json_and_sends_user_agent(make_client):
    handler = Scripted(ok({"departments": [{"id": 1}]}))
    with make_client(handler) as client:
        assert client.get_json(URL) == {"departments": [{"id": 1}]}
    assert handler.requests[0].headers["User-Agent"] == USER_AGENT
    assert USER_AGENT == (
        "JobSignal/0.1 (+https://github.com/LionyRamli/JobSignal; academic research)"
    )


def test_query_params_are_sent(make_client):
    handler = Scripted(ok())
    make_client(handler).get_json(URL, params={"content": "true"})
    assert handler.requests[0].url.params["content"] == "true"


def test_retries_503_then_succeeds_with_exponential_delays(make_client, sleeps):
    handler = Scripted(httpx.Response(503), httpx.Response(503), ok())
    assert make_client(handler).get_json(URL) == OK
    assert sleeps == [1.0, 2.0]


def test_default_attempts_then_retry_exhausted(make_client, sleeps):
    handler = Scripted(*[httpx.Response(503) for _ in range(4)])
    with pytest.raises(RetryExhaustedError) as excinfo:
        make_client(handler).get_json(URL)
    assert excinfo.value.last_status == 503
    assert len(handler.requests) == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_backoff_is_capped(make_client, sleeps):
    handler = Scripted(*[httpx.Response(503) for _ in range(5)])
    with pytest.raises(RetryExhaustedError):
        make_client(handler, max_attempts=5, backoff_cap=3).get_json(URL)
    assert sleeps == [1.0, 2.0, 3.0, 3.0]


def test_backoff_uses_full_jitter(sleeps):
    handler = Scripted(httpx.Response(503), httpx.Response(503), ok())
    client = HttpClient(
        transport=httpx.MockTransport(handler),
        rate_limiter=RateLimiter(0),
        sleep=sleeps.append,
        rand=lambda: 0.25,
    )
    client.get_json(URL)
    assert sleeps == [0.25, 0.5]


def test_retry_after_is_honoured(make_client, sleeps):
    handler = Scripted(httpx.Response(429, headers={"Retry-After": "7"}), ok())
    make_client(handler).get_json(URL)
    assert sleeps == [7.0]


def test_retry_after_is_capped(make_client, sleeps):
    handler = Scripted(httpx.Response(429, headers={"Retry-After": "3600"}), ok())
    make_client(handler).get_json(URL)
    assert sleeps == [30.0]


@pytest.mark.parametrize("value", ["Wed, 21 Oct 2026 07:28:00 GMT", "-5", "soon", "", "1.5"])
def test_unparseable_retry_after_falls_back_to_backoff(make_client, sleeps, value):
    handler = Scripted(httpx.Response(503, headers={"Retry-After": value}), ok())
    make_client(handler).get_json(URL)
    assert sleeps == [1.0]


def test_transport_error_is_retried(make_client, sleeps):
    handler = Scripted(httpx.ConnectError("refused"), ok())
    assert make_client(handler).get_json(URL) == OK
    assert len(handler.requests) == 2
    assert sleeps == [1.0]


def test_timeout_is_retried(make_client):
    handler = Scripted(httpx.ReadTimeout("slow"), ok())
    assert make_client(handler).get_json(URL) == OK


def test_exhausted_network_errors_have_no_status(make_client):
    handler = Scripted(*[httpx.ConnectError("down") for _ in range(4)])
    with pytest.raises(RetryExhaustedError) as excinfo:
        make_client(handler).get_json(URL)
    assert excinfo.value.last_status is None


def test_404_raises_source_not_found_without_retry(make_client, sleeps):
    handler = Scripted(httpx.Response(404))
    with pytest.raises(SourceNotFoundError):
        make_client(handler).get_json(URL)
    assert len(handler.requests) == 1
    assert sleeps == []


@pytest.mark.parametrize("status", [400, 401, 403, 301])
def test_other_non_success_status_is_not_retried(make_client, sleeps, status):
    handler = Scripted(httpx.Response(status, headers={"Location": "https://evil.example/"}))
    with pytest.raises(ExtractionError) as excinfo:
        make_client(handler).get_json(URL)
    assert not isinstance(excinfo.value, RetryExhaustedError | SourceNotFoundError)
    assert len(handler.requests) == 1
    assert sleeps == []


def test_non_json_200_raises_invalid_payload(make_client):
    handler = Scripted(httpx.Response(200, text="<html>Maintenance</html>"))
    with pytest.raises(InvalidPayloadError):
        make_client(handler).get_json(URL)


def test_oversized_body_rejected_while_streaming(make_client):
    body = iter([b'{"departments": [' + b" " * 400, b" " * 600 + b"]}"])
    handler = Scripted(httpx.Response(200, content=body))  # chunked: no Content-Length
    with pytest.raises(ResponseTooLargeError):
        make_client(handler, max_response_bytes=100).get_json(URL)


def test_oversized_content_length_rejected(make_client):
    handler = Scripted(httpx.Response(200, content=b"{}" + b" " * 998))
    with pytest.raises(ResponseTooLargeError):
        make_client(handler, max_response_bytes=100).get_json(URL)


def test_declared_oversize_rejected_before_reading_body(make_client):
    def body_must_not_be_read():
        raise AssertionError("body was downloaded despite oversized Content-Length")
        yield b""  # pragma: no cover

    response = httpx.Response(
        200, headers={"Content-Length": "5000"}, content=body_must_not_be_read()
    )
    with pytest.raises(ResponseTooLargeError):
        make_client(Scripted(response), max_response_bytes=100).get_json(URL)


def test_body_at_limit_is_accepted(make_client):
    payload = b'{"a": 1}'
    handler = Scripted(httpx.Response(200, content=payload))
    assert make_client(handler, max_response_bytes=len(payload)).get_json(URL) == {"a": 1}


@pytest.mark.parametrize("url", ["http://boards-api.greenhouse.io/v1", "file:///etc/passwd"])
def test_non_https_url_rejected(make_client, url):
    handler = Scripted()
    with pytest.raises(ValueError, match="https"):
        make_client(handler).get_json(url)
    assert handler.requests == []


def test_invalid_max_attempts_rejected():
    with pytest.raises(ValueError, match="max_attempts"):
        HttpClient(max_attempts=0)


def test_rate_limiter_consulted_on_every_attempt(make_client):
    limiter = SpyLimiter()
    handler = Scripted(httpx.Response(503), ok())
    make_client(handler, rate_limiter=limiter).get_json(URL)
    assert limiter.waits == ["boards-api.greenhouse.io"] * 2


def test_retry_logs_warning_and_exhaustion_logs_error(make_client, caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("jobsignal"), "propagate", True)
    handler = Scripted(*[httpx.Response(503) for _ in range(2)])
    with (
        caplog.at_level(logging.INFO, logger="jobsignal.extraction.http_client"),
        pytest.raises(RetryExhaustedError),
    ):
        make_client(handler, max_attempts=2).get_json(URL)

    records = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert [level for level, _ in records] == ["WARNING", "ERROR"]
    assert "503" in records[0][1]
    assert "attempt 1/2" in records[0][1]
    assert URL in records[1][1]


def test_absurdly_long_retry_after_is_capped_not_crashing(make_client, sleeps):
    handler = Scripted(httpx.Response(429, headers={"Retry-After": "9" * 5000}), ok())
    assert make_client(handler).get_json(URL) == OK
    assert sleeps == [30.0]


def test_non_ascii_digit_retry_after_falls_back_to_backoff(make_client, sleeps):
    superscript_two = "²".encode()  # str.isdigit() is True for it, int() is not
    handler = Scripted(httpx.Response(503, headers={"Retry-After": superscript_two}), ok())
    make_client(handler).get_json(URL)
    assert sleeps == [1.0]


def test_corrupt_compressed_body_raises_invalid_payload(make_client):
    handler = Scripted(
        httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, content=iter([b"not gzip at all"])
        )
    )
    with pytest.raises(InvalidPayloadError):
        make_client(handler).get_json(URL)


def test_deeply_nested_json_raises_invalid_payload(make_client):
    handler = Scripted(httpx.Response(200, content=b"[" * 100_000))
    with pytest.raises(InvalidPayloadError):
        make_client(handler).get_json(URL)
