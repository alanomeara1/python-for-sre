"""SLO helpers: percentile, availability, error budget, burn-rate paging.

Spec: drills/09_slo_math/README.md
"""

from typing import Iterable


def percentile(values: Iterable[float], p: float) -> float:
    raise NotImplementedError


def availability(good: int, total: int) -> float:
    raise NotImplementedError


def error_budget_remaining(slo: float, good: int, total: int) -> float:
    raise NotImplementedError


def burn_rate(slo: float, error_rate: float) -> float:
    raise NotImplementedError


def should_page(slo: float, short_window_error_rate: float,
                long_window_error_rate: float, threshold: float = 14.4) -> bool:
    raise NotImplementedError
