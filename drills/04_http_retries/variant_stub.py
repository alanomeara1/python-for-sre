"""A reusable @retry decorator with capped exponential backoff.

Spec: drills/04_http_retries/variant.md
"""

import functools
import logging
import time
from typing import Callable

log = logging.getLogger(__name__)


def retry(exceptions: tuple[type[BaseException], ...] = (Exception,), attempts: int = 3,
          base_delay: float = 0.1, max_delay: float = 5.0,
          sleep: Callable[[float], None] = time.sleep):
    raise NotImplementedError
