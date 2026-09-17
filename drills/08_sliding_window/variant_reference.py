"""Token bucket rate limiter, single and per key."""

from collections import defaultdict


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: float):
        self.rate = rate_per_sec
        self.capacity = capacity
        self.tokens = float(capacity)     # start full: new clients aren't throttled
        self.last: float | None = None    # latest time seen

    def _refill(self, now: float) -> None:
        if self.last is None:
            self.last = now
            return
        # Clock went backwards: grant nothing, and keep the LATEST time so the
        # jump forward again doesn't pay out the same interval twice.
        elapsed = max(0.0, now - self.last)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last = max(self.last, now)

    def allow(self, now: float, cost: float = 1) -> bool:
        self._refill(now)
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False                      # rejected requests consume nothing


class KeyedLimiter:
    def __init__(self, rate_per_sec: float, capacity: float):
        # The lambda builds a NEW bucket for each new key.
        self.buckets = defaultdict(lambda: TokenBucket(rate_per_sec, capacity))

    def allow(self, key: str, now: float, cost: float = 1) -> bool:
        return self.buckets[key].allow(now, cost)
