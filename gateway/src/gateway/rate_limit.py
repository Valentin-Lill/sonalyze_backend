from __future__ import annotations

import time


class TokenBucket:
    def __init__(self, rate_per_second: float, capacity: int) -> None:
        self._rate = max(rate_per_second, 0.0)
        self._capacity = max(int(capacity), 1)
        self._tokens = float(self._capacity)
        self._last = time.monotonic()

    def allow(self, tokens: float = 1.0) -> bool:
        now = time.monotonic()
        elapsed = max(now - self._last, 0.0)
        self._last = now

        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False
