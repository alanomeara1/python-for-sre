"""SLO helpers: percentile, availability, error budget, burn-rate paging.

Budget = 1 - SLO. Burn rate = error rate / budget. Page when a long AND a short
window both burn fast. Every function below is one of those sentences.
Full reasoning in EXPLAINED.md.
"""

import math
from typing import Iterable


def percentile(values: Iterable[float], p: float) -> float:
    # Validate the cheap thing first: an out-of-range p is a caller bug, not a data case.
    if not 0 <= p <= 100:
        raise ValueError(f"percentile must be in [0, 100], got {p}")
    # `if not values` is ALWAYS false for a generator (the object is truthy), so sort
    # first to materialise it, then test the list.
    ordered = sorted(values)              # sort first: works for generators too
    if not ordered:
        raise ValueError("percentile of empty data")

    # Nearest-rank returns a latency somebody actually experienced; interpolated methods
    # (numpy's default) can report a number no request ever took. Either is defensible,
    # as long as you say which you used.
    # Nearest-rank. Multiply before dividing: 7 / 100 * 100 == 7.000000000000001.
    # max(1, ...) because at p=0 the rank is 0 and ordered[-1] is the LARGEST value.
    rank = max(1, math.ceil(p * len(ordered) / 100))
    # Ranks are 1-based, indices are 0-based. float() so int input still returns a float.
    return float(ordered[rank - 1])


def availability(good: int, total: int) -> float:
    # No requests means nothing failed, so 100% keeps a quiet service off the incident
    # dashboard. ("No traffic" being its own emergency is what a no-data alert is for.)
    return good / total if total else 1.0


def error_budget_remaining(slo: float, good: int, total: int) -> float:
    # Exclusive bounds catch both nonsense cases: slo=1.0 has a zero budget (divide by
    # zero, and every deploy is a violation), and slo=99.9 is percent-instead-of-fraction,
    # the most likely caller mistake.
    if not 0 < slo < 1:
        raise ValueError(f"SLO must be between 0 and 1 exclusive, got {slo}")
    if total == 0:
        return 1.0

    budget = 1 - slo                      # fraction of requests allowed to fail
    error_rate = (total - good) / total
    # error_rate / budget is the fraction of the allowance used, i.e. the burn rate;
    # 1 minus that is what's left. A FRACTION, not a request count, so it compares
    # across services. Negatives pass through: -1.0 means you burned twice the budget,
    # and clamping would discard what triggers a feature freeze.
    return 1 - error_rate / budget        # negative means overspent


def burn_rate(slo: float, error_rate: float) -> float:
    # 30 days = 720 hours, so spending 2% of the budget in 1 hour is x/720 = 0.02 -> 14.4.
    # (No slo validation here, unlike above: burn_rate(1.0, ...) raises ZeroDivisionError.)
    # 1.0 spends the budget exactly over the SLO period; 14.4 spends 2% of 30 days in 1h.
    return error_rate / (1 - slo)


def should_page(slo: float, short_window_error_rate: float,
                long_window_error_rate: float, threshold: float = 14.4) -> bool:
    # AND, never OR. Long window alone keeps paging for an hour after the fix, because
    # the bad data is still in the window. Short window alone pages on every blip that
    # recovers before you open the laptop. Together: significant AND ongoing, and the
    # alert clears soon after the fix because the short window empties quickly.
    # threshold is a parameter because the workbook defines a ladder: 14.4 over 1h/5m
    # pages, 6 over 6h/30m pages, 1 over 3d/6h raises a ticket.
    # Long window: it's significant. Short window: it's still happening.
    return (burn_rate(slo, long_window_error_rate) >= threshold
            and burn_rate(slo, short_window_error_rate) >= threshold)
