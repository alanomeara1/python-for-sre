"""Sliding-window error-rate monitor and per-client rate limiter.

Spec: drills/08_sliding_window/README.md
"""


class ErrorRateMonitor:
    def __init__(self, window_seconds: float, threshold: float, min_requests: int = 1):
        raise NotImplementedError

    def record(self, timestamp: float, ok: bool) -> None:
        raise NotImplementedError

    def error_rate(self, now: float) -> float:
        raise NotImplementedError

    def should_alert(self, now: float) -> bool:
        raise NotImplementedError


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        raise NotImplementedError

    def allow(self, client_id: str, now: float) -> bool:
        raise NotImplementedError
