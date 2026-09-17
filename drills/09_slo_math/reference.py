"""SLO helpers: percentile, availability, error budget, burn-rate paging."""

import math
from typing import Iterable


def percentile(values: Iterable[float], p: float) -> float:
    if not 0 <= p <= 100:
        raise ValueError(f"percentile must be in [0, 100], got {p}")
    ordered = sorted(values)              # sort first: works for generators too
    if not ordered:
        raise ValueError("percentile of empty data")

    # Nearest-rank. Multiply before dividing: 7 / 100 * 100 == 7.000000000000001.
    rank = max(1, math.ceil(p * len(ordered) / 100))
    return float(ordered[rank - 1])


def availability(good: int, total: int) -> float:
    return good / total if total else 1.0


def error_budget_remaining(slo: float, good: int, total: int) -> float:
    if not 0 < slo < 1:
        raise ValueError(f"SLO must be between 0 and 1 exclusive, got {slo}")
    if total == 0:
        return 1.0

    budget = 1 - slo                      # fraction of requests allowed to fail
    error_rate = (total - good) / total
    return 1 - error_rate / budget        # negative means overspent


def burn_rate(slo: float, error_rate: float) -> float:
    # 1.0 spends the budget exactly over the SLO period; 14.4 spends 2% of 30 days in 1h.
    return error_rate / (1 - slo)


def should_page(slo: float, short_window_error_rate: float,
                long_window_error_rate: float, threshold: float = 14.4) -> bool:
    # Long window: it's significant. Short window: it's still happening.
    return (burn_rate(slo, long_window_error_rate) >= threshold
            and burn_rate(slo, short_window_error_rate) >= threshold)
