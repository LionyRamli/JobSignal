"""Shared, hardened HTTP client for every ATS source.

Owns all network politeness and failure handling so sources only parse:
per-host rate limiting, retries with capped exponential backoff (full jitter),
``Retry-After`` support, strict timeouts, a response-size cap, https-only URLs,
no redirects, and mapping of HTTP failures onto ``jobsignal.extraction.errors``.
"""

import json
import logging
import random
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

import httpx

from jobsignal.extraction.errors import (
    ExtractionError,
    InvalidPayloadError,
    ResponseTooLargeError,
    RetryExhaustedError,
    SourceNotFoundError,
)
from jobsignal.extraction.rate_limit import RateLimiter

logger = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
USER_AGENT = "JobSignal/0.1 (+https://github.com/LionyRamli/JobSignal; academic research)"
DEFAULT_MIN_INTERVAL = 2.0
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
MAX_RETRY_AFTER_DIGITS = 9


class _Retryable(Exception):  # noqa: N818 - internal control-flow signal, not an error
    def __init__(self, status: int | None, reason: str, retry_after: str | None = None) -> None:
        self.status = status
        self.reason = reason
        self.retry_after = retry_after


class HttpClient:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        rate_limiter: RateLimiter | None = None,
        max_attempts: int = 4,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
        max_response_bytes: int = 10_000_000,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[], float] = random.random,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self._rate_limiter = rate_limiter or RateLimiter(DEFAULT_MIN_INTERVAL)
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._max_response_bytes = max_response_bytes
        self._sleep = sleep
        self._rand = rand
        self._client = httpx.Client(
            transport=transport,
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        """GET ``url`` and return the decoded JSON body, retrying transient failures."""
        parsed = httpx.URL(url)
        if parsed.scheme != "https":
            raise ValueError(f"only https URLs are allowed, got {url!r}")

        last = _Retryable(None, "no attempt made")
        for attempt in range(self._max_attempts):
            self._rate_limiter.wait(parsed.host)
            try:
                return self._attempt(url, params)
            except _Retryable as retryable:
                last = retryable
            if attempt + 1 < self._max_attempts:
                delay = self._delay(attempt, last.retry_after)
                logger.warning(
                    "GET %s failed (%s); retrying in %.1fs (attempt %d/%d)",
                    url,
                    last.reason,
                    delay,
                    attempt + 1,
                    self._max_attempts,
                )
                self._sleep(delay)

        logger.error("GET %s gave up after %d attempts (%s)", url, self._max_attempts, last.reason)
        raise RetryExhaustedError(last.status, f"GET {url} failed: {last.reason}")

    def _attempt(self, url: str, params: dict[str, str] | None) -> Any:
        try:
            with self._client.stream("GET", url, params=params) as response:
                status = response.status_code
                if status in RETRYABLE_STATUSES:
                    raise _Retryable(status, f"HTTP {status}", response.headers.get("Retry-After"))
                if status == 404:
                    raise SourceNotFoundError(f"GET {url} returned 404")
                if not 200 <= status < 300:
                    raise ExtractionError(f"GET {url} returned HTTP {status}")
                body = self._read_capped(response, url)
        except httpx.DecodingError as exc:  # e.g. corrupt gzip from a misbehaving proxy
            raise InvalidPayloadError(f"GET {url}: undecodable response body") from exc
        except httpx.TransportError as exc:  # includes timeouts
            raise _Retryable(None, type(exc).__name__) from exc

        try:
            return json.loads(body)
        except (ValueError, RecursionError) as exc:  # RecursionError: deeply nested input
            raise InvalidPayloadError(f"GET {url} did not return valid JSON") from exc

    def _read_capped(self, response: httpx.Response, url: str) -> bytes:
        limit = self._max_response_bytes
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > limit:
            raise ResponseTooLargeError(f"GET {url}: Content-Length {declared} > {limit}")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > limit:
                raise ResponseTooLargeError(f"GET {url}: body exceeded {limit} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            value = retry_after.strip()
            # Seconds form only (ASCII digits); HTTP-dates, negatives, decimals fall back.
            if value.isascii() and value.isdigit():
                if len(value) > MAX_RETRY_AFTER_DIGITS:  # int() refuses >4300 digits
                    return float(self._backoff_cap)
                return float(min(int(value), self._backoff_cap))
        return self._rand() * min(self._backoff_cap, self._backoff_base * 2**attempt)
