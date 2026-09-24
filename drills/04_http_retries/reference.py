"""GET with retries: exponential backoff, 5xx/429 handling, Retry-After.

Three questions in order: what's worth retrying, how long to wait, when to stop. A retry
loop is a load amplifier, which is why delays grow and 4xx never repeats. See EXPLAINED.md.
"""

import time
from typing import Callable

import requests

# A named ceiling, not a magic number: it bounds both our own backoff and anything a
# server asks for via Retry-After.
MAX_DELAY = 30.0


class RetryError(Exception):
    # Its own type so callers can catch THIS failure without catching their own bugs too.
    pass


def backoff_delays(base: float, attempts: int, cap: float,
                   rng: Callable[[], float] | None = None) -> list[float]:
    # Pulled out as a pure function: a list of numbers is trivial to test, "did it sleep the
    # right amount inside a network loop" is not.
    delays = []
    for i in range(attempts):                # attempts=0 gives [], no special case needed
        # Double each time, but never past the cap, or attempt 10 waits eight minutes.
        delay = min(base * 2 ** i, cap)
        if rng is not None:
            # Full jitter spreads clients out so they don't all retry in lock-step.
            # Injected, not random.random(), so tests can assert exact delays.
            delay *= rng()
        delays.append(delay)
    return delays


def _should_retry(status: int) -> bool:
    # 429 = "slow down", 5xx = "server's fault". Other 4xx will fail the same way forever.
    # The whole policy in one named line, so the loop below reads as prose.
    return status == 429 or status >= 500


def fetch_with_retry(url: str, attempts: int = 3, base_delay: float = 0.5, timeout: float = 2.0,
                     sleep: Callable[[float], None] = time.sleep,
                     session: requests.Session | None = None) -> requests.Response:
    # sleep is a parameter so tests run instantly and can assert the exact delays.
    # A Session reuses the TCP connection across attempts, and lets a caller supply auth or a fake.
    session = session or requests.Session()
    # attempts - 1: three attempts have two gaps between them. This is the off-by-one to watch.
    delays = backoff_delays(base_delay, attempts - 1, MAX_DELAY)
    last_error = "no attempts made"

    for attempt in range(1, attempts + 1):   # 1-based, so `attempt == attempts` reads as "last one"
        retry_after = None
        try:
            response = session.get(url, timeout=timeout)     # never without a timeout
        except (requests.ConnectionError, requests.Timeout) as exc:
            # Two specific types, not bare Exception: a TypeError in our own code must not be
            # retried three times and then reported as a network failure.
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            # else runs only when .get() didn't raise, so this handling can't be caught above.
            if not _should_retry(response.status_code):
                return response                              # success, or a 4xx the caller must handle
            last_error = f"HTTP {response.status_code}"
            retry_after = response.headers.get("Retry-After")

        if attempt == attempts:
            break                                            # don't sleep just to give up

        delay = delays[attempt - 1]                          # attempt is 1-based, lists are 0-based
        # isdigit() because Retry-After may also be an HTTP date; handle the numeric form only.
        if retry_after and retry_after.isdigit():
            delay = min(float(retry_after), MAX_DELAY)       # the server knows best, within reason
        sleep(delay)

    # Name the attempts and the last error, so the log line explains itself.
    raise RetryError(f"GET {url} failed after {attempts} attempts; last error: {last_error}")
