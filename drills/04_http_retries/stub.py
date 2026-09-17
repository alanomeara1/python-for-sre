"""GET with retries: exponential backoff, 5xx/429 handling, Retry-After.

Spec: drills/04_http_retries/README.md
"""

import time
from typing import Callable

import requests

MAX_DELAY = 30.0


class RetryError(Exception):
    pass


def backoff_delays(base: float, attempts: int, cap: float,
                   rng: Callable[[], float] | None = None) -> list[float]:
    raise NotImplementedError


def fetch_with_retry(url: str, attempts: int = 3, base_delay: float = 0.5, timeout: float = 2.0,
                     sleep: Callable[[float], None] = time.sleep,
                     session: requests.Session | None = None) -> requests.Response:
    raise NotImplementedError
