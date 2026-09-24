"""Sliding-window error-rate monitor and per-client rate limiter.

One data structure, two questions. Every operation is the same two beats:
evict from the left, then answer. Full reasoning in EXPLAINED.md.
"""

from collections import defaultdict, deque


class ErrorRateMonitor:
    def __init__(self, window_seconds: float, threshold: float, min_requests: int = 1):
        self.window = window_seconds
        self.threshold = threshold
        # A significance floor: without it, one failed health check on a quiet night
        # is a 100% error rate and someone gets paged at 3am.
        self.min_requests = min_requests
        # deque, not list: popleft() is O(1) where list.pop(0) shifts every element.
        # (timestamp, ok) pairs in one deque, because two parallel deques can drift.
        self.events: deque[tuple[float, bool]] = deque()   # oldest on the left
        # The point of the drill: sum(...) per query is O(window), which at 10k rps
        # over 60s is 600k iterations PER CALL. A running count makes queries O(1),
        # at the cost of maintaining it in two places (here and in _evict).
        self.errors = 0                                    # running count, never re-scan

    def record(self, timestamp: float, ok: bool) -> None:
        # No eviction here: an event doesn't know what time it is "now". Queries evict,
        # so the window is always correct at the moment anyone looks at it.
        self.events.append((timestamp, ok))
        if not ok:
            self.errors += 1

    def _evict(self, now: float) -> None:
        # An event at t is in the window while now - window < t, so evict t <= now - window.
        cutoff = now - self.window
        # `self.events and ...` first: `and` short-circuits, and checking events[0] on an
        # empty deque raises IndexError. `while`, not `if`: an idle gap expires many at once.
        while self.events and self.events[0][0] <= cutoff:
            _, ok = self.events.popleft()
            # The decrement that pairs with record()'s increment. Forget it and the error
            # rate only ever climbs.
            if not ok:
                self.errors -= 1

    def error_rate(self, now: float) -> float:
        self._evict(now)
        # No requests means no errors, not a crash. len(deque) is O(1).
        return self.errors / len(self.events) if self.events else 0.0

    def should_alert(self, now: float) -> bool:
        rate = self.error_rate(now)                        # evicts first
        # Order matters: reading len() before error_rate() would count expired events.
        # >= on both, so "alert at 10%" fires at exactly 10%.
        # Don't page on 1 failure out of 1 request.
        return len(self.events) >= self.min_requests and rate >= self.threshold


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        # The factory `deque` is called per missing key, so each client gets its own.
        # Passing an already-built deque() would share one queue between everyone.
        self.hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, client_id: str, now: float) -> bool:
        # Bind once: this is a dict lookup plus a possible factory call.
        hits = self.hits[client_id]
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()

        # >= not >: limit=3 means the third is allowed and the fourth is not.
        if len(hits) >= self.limit:
            return False              # rejected requests are not recorded
        # Recording rejections would let a client retrying in a tight loop refill its own
        # window and stay locked out forever. Only what we actually served counts.
        hits.append(now)
        return True
