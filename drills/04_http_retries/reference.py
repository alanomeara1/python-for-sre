"""GET with retries: exponential backoff, 5xx/429 handling, Retry-After."""

import time
from typing import Callable

import requests

MAX_DELAY = 30.0


class RetryError(Exception):
    pass


def backoff_delays(base: float, attempts: int, cap: float,
                   rng: Callable[[], float] | None = None) -> list[float]:
    delays = []
    for i in range(attempts):
        delay = min(base * 2 ** i, cap)
        if rng is not None:
            # Full jitter spreads clients out so they don't all retry in lock-step.
            delay *= rng()
        delays.append(delay)
    return delays


def _should_retry(status: int) -> bool:
    # 429 = "slow down", 5xx = "server's fault". Other 4xx will fail the same way forever.
    return status == 429 or status >= 500


def fetch_with_retry(url: str, attempts: int = 3, base_delay: float = 0.5, timeout: float = 2.0,
                     sleep: Callable[[float], None] = time.sleep,
                     session: requests.Session | None = None) -> requests.Response:
    session = session or requests.Session()
    delays = backoff_delays(base_delay, attempts - 1, MAX_DELAY)
    last_error = "no attempts made"

    for attempt in range(1, attempts + 1):
        retry_after = None
        try:
            response = session.get(url, timeout=timeout)     # never without a timeout
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if not _should_retry(response.status_code):
                return response                              # success, or a 4xx the caller must handle
            last_error = f"HTTP {response.status_code}"
            retry_after = response.headers.get("Retry-After")

        if attempt == attempts:
            break                                            # don't sleep just to give up

        delay = delays[attempt - 1]
        if retry_after and retry_after.isdigit():
            delay = min(float(retry_after), MAX_DELAY)       # the server knows best, within reason
        sleep(delay)

    raise RetryError(f"GET {url} failed after {attempts} attempts; last error: {last_error}")
