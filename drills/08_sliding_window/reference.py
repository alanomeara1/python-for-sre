"""Sliding-window error-rate monitor and per-client rate limiter."""

from collections import defaultdict, deque


class ErrorRateMonitor:
    def __init__(self, window_seconds: float, threshold: float, min_requests: int = 1):
        self.window = window_seconds
        self.threshold = threshold
        self.min_requests = min_requests
        self.events: deque[tuple[float, bool]] = deque()   # oldest on the left
        self.errors = 0                                    # running count, never re-scan

    def record(self, timestamp: float, ok: bool) -> None:
        self.events.append((timestamp, ok))
        if not ok:
            self.errors += 1

    def _evict(self, now: float) -> None:
        # An event at t is in the window while now - window < t, so evict t <= now - window.
        cutoff = now - self.window
        while self.events and self.events[0][0] <= cutoff:
            _, ok = self.events.popleft()
            if not ok:
                self.errors -= 1

    def error_rate(self, now: float) -> float:
        self._evict(now)
        return self.errors / len(self.events) if self.events else 0.0

    def should_alert(self, now: float) -> bool:
        rate = self.error_rate(now)                        # evicts first
        # Don't page on 1 failure out of 1 request.
        return len(self.events) >= self.min_requests and rate >= self.threshold


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self.hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, client_id: str, now: float) -> bool:
        hits = self.hits[client_id]
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            return False              # rejected requests are not recorded
        hits.append(now)
        return True
