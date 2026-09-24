"""Token bucket rate limiter, single and per key.

Two floats per client instead of a queue of timestamps: constant memory whatever
the traffic, in exchange for allowing a burst up to capacity before smoothing to
rate. Full reasoning in EXPLAINED.md.
"""

from collections import defaultdict


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: float):
        self.rate = rate_per_sec
        self.capacity = capacity
        self.tokens = float(capacity)     # start full: new clients aren't throttled
        self.last: float | None = None    # latest time seen

    def _refill(self, now: float) -> None:
        # First call just anchors the clock: there's no elapsed interval to mint yet.
        if self.last is None:
            self.last = now
            return
        # Clock went backwards: grant nothing, and keep the LATEST time so the
        # jump forward again doesn't pay out the same interval twice.
        # NTP steps, VM migrations and leap-second smearing all cause this. In
        # production you'd feed this time.monotonic(), which cannot go backwards.
        elapsed = max(0.0, now - self.last)
        # Lazy refill: no background thread, no timers, O(1) per call. min() caps a long
        # idle period from granting an unlimited burst.
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last = max(self.last, now)

    def allow(self, now: float, cost: float = 1) -> bool:
        self._refill(now)
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        # A cost above capacity can never succeed, however long you wait: reject that at
        # the API layer with a clear error rather than letting the caller retry forever.
        return False                      # rejected requests consume nothing


class KeyedLimiter:
    def __init__(self, rate_per_sec: float, capacity: float):
        # The lambda builds a NEW bucket for each new key.
        # It also closes over the settings, which a bare `defaultdict(TokenBucket)`
        # can't do. `defaultdict(lambda: shared_bucket)` would hand everyone the same
        # bucket, so one noisy client throttles the whole estate.
        self.buckets = defaultdict(lambda: TokenBucket(rate_per_sec, capacity))

    def allow(self, key: str, now: float, cost: float = 1) -> bool:
        return self.buckets[key].allow(now, cost)
