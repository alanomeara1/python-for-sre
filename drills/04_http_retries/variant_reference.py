"""A reusable @retry decorator with capped exponential backoff.

Same policy as fetch_with_retry, packaged for any callable. The three-layer shape
(options -> function -> call) is what every decorator-with-arguments looks like.
Reasoning in EXPLAINED.md.
"""

import functools
import logging
import time
from typing import Callable

log = logging.getLogger(__name__)


def retry(exceptions: tuple[type[BaseException], ...] = (Exception,), attempts: int = 3,
          base_delay: float = 0.1, max_delay: float = 5.0,
          sleep: Callable[[float], None] = time.sleep):
    # Layer 1 takes the OPTIONS. The caller chooses which exceptions count, so a bug of their
    # own (ValueError, TypeError) propagates instead of being retried and buried.
    # Fail at decoration (import) time, not on the first failure in production.
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    def decorator(func):
        # Layer 2 takes the FUNCTION being decorated.
        @functools.wraps(func)                   # keep func's name/docstring for logs and tracebacks
        def wrapper(*args, **kwargs):
            # Layer 3 takes the CALL. *args/**kwargs pass anything through untouched.
            for attempt in range(1, attempts + 1):
                # Attribute on the function object: handy as a rough metric, but it's shared
                # state, so treat it as an indicator rather than a per-call count.
                wrapper.last_attempts = attempt
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts:
                        raise                    # bare raise keeps the original traceback
                    # Same curve as backoff_delays: double each time, capped.
                    delay = min(base_delay * 2 ** (attempt - 1), max_delay)
                    # %s placeholders: logging formats only if the record is emitted.
                    log.warning("%s failed (%s), attempt %d/%d, retrying in %.2fs",
                                func.__name__, exc, attempt, attempts, delay)
                    sleep(delay)

        wrapper.last_attempts = 0
        return wrapper

    return decorator
