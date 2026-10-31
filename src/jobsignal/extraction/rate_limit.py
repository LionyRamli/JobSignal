"""Per-host politeness: never hit the same host more often than once per ``min_interval``."""

import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if min_interval < 0:
            raise ValueError("min_interval must be >= 0")
        self._min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last_request: dict[str, float] = {}

    def wait(self, host: str) -> None:
        """Block until a request to ``host`` is allowed, then record it."""
        last = self._last_request.get(host)
        if last is not None:
            remaining = self._min_interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request[host] = self._clock()
