"""Token bucket rate limiter, single and per key.

Spec: drills/08_sliding_window/variant.md
"""


class TokenBucket:
    def __init__(self, rate_per_sec: float, capacity: float):
        raise NotImplementedError

    def allow(self, now: float, cost: float = 1) -> bool:
        raise NotImplementedError


class KeyedLimiter:
    def __init__(self, rate_per_sec: float, capacity: float):
        raise NotImplementedError

    def allow(self, key: str, now: float, cost: float = 1) -> bool:
        raise NotImplementedError
