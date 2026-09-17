"""A reusable @retry decorator with capped exponential backoff."""

import functools
import logging
import time
from typing import Callable

log = logging.getLogger(__name__)


def retry(exceptions: tuple[type[BaseException], ...] = (Exception,), attempts: int = 3,
          base_delay: float = 0.1, max_delay: float = 5.0,
          sleep: Callable[[float], None] = time.sleep):
    # Fail at decoration (import) time, not on the first failure in production.
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    def decorator(func):
        @functools.wraps(func)                   # keep func's name/docstring for logs and tracebacks
        def wrapper(*args, **kwargs):
            for attempt in range(1, attempts + 1):
                wrapper.last_attempts = attempt
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts:
                        raise                    # bare raise keeps the original traceback
                    delay = min(base_delay * 2 ** (attempt - 1), max_delay)
                    log.warning("%s failed (%s), attempt %d/%d, retrying in %.2fs",
                                func.__name__, exc, attempt, attempts, delay)
                    sleep(delay)

        wrapper.last_attempts = 0
        return wrapper

    return decorator
