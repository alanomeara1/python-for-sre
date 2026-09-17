# 09 · SLO math: percentiles, error budgets, burn-rate paging

**Why this drill:** For an SRE *Manager*, this is the drill where the code is easy and the
conversation is the interview. You'll be asked what p99 means, what's left of the error budget,
and when to page. Writing it cold, correctly, while explaining multiwindow burn-rate alerts
is a strong signal.

## The task, as an interviewer would say it

> Give me a few helpers for our SLO dashboard: a latency percentile, availability, how much
> error budget is left, the burn rate, and a function that decides whether to page using the
> multiwindow burn-rate approach from the SRE workbook.

## Background you must be able to say from memory

- **SLO** 99.9% → **error budget** = `1 - 0.999` = 0.1% of requests may fail.
- **Burn rate** = observed error rate ÷ error budget. Burn rate 1 spends exactly the whole budget
  over the SLO period (e.g. 30 days). Burn rate 14.4 spends **2% of a 30-day budget in 1 hour**
  (`14.4 × 1h / 720h = 0.02`).
- **Multiwindow**: page only if **both** the long window (e.g. 1h) **and** a short window
  (e.g. 5m) are burning at ≥ the threshold. The long window proves it's significant. The short
  window proves it's *still happening*, so the alert resets quickly once you've fixed it.
  The workbook's other tiers: 6 for 6h/30m (page), 1 for 3d/6h (ticket).

## Contract (what the tests call)

```python
def percentile(values: Iterable[float], p: float) -> float
    # Nearest-rank: sort, rank = ceil(p * n / 100), min rank 1, return ordered[rank - 1].
    # ValueError if there are no values or p is outside [0, 100].

def availability(good: int, total: int) -> float
    # good / total; 1.0 when total == 0 (no requests, nothing failed)

def error_budget_remaining(slo: float, good: int, total: int) -> float
    # 1.0 = untouched, 0.0 = exactly spent, negative = overspent.
    # 1.0 when total == 0. ValueError unless 0 < slo < 1.

def burn_rate(slo: float, error_rate: float) -> float

def should_page(slo: float, short_window_error_rate: float,
                long_window_error_rate: float, threshold: float = 14.4) -> bool
    # True only when BOTH windows burn at >= threshold
```

## Patterns you are drilling

- `math.ceil(p * n / 100)`: multiply **before** dividing. `7 / 100 * 100` is `7.000000000000001`.
- `ordered = sorted(values)` *then* check emptiness, so a generator input works
- Raise `ValueError` with a message for impossible input. Don't return a misleading `0`.
- Build the bigger functions from the small ones (`should_page` calls `burn_rate`)

## Say this out loud (what the interviewer listens for)

- "Nearest-rank always returns a real observed value. Interpolated methods (numpy's default) can
  return a latency nobody experienced. Either's fine, as long as you say which."
- "You can't average percentiles across hosts. Merge the histograms, then take the percentile.
  That's why Prometheus uses `histogram_quantile` over summed buckets."
- "A 100% SLO has zero error budget: every deploy is a violation and nobody can ship. So I raise on it."
- "Negative budget remaining is information, not an error. It's what triggers a feature freeze under the error budget policy."
- "Paging on a raw error-rate threshold is either too noisy or too slow. Burn rate ties the page to
  what actually matters, which is how fast we're spending the budget."

## Traps

- `p / 100 * n` float error pushes the rank up by one at exact boundaries.
- `if not values:` on a generator is always truthy. Sort first.
- `1 - 0.999` is `0.0010000000000000009`. Compare floats with a tolerance, and don't put a test
  exactly on a threshold boundary.
- Using `or` instead of `and` in `should_page`, which pages on every short blip.
- Swapping short/long argument order. Keyword arguments at the call site make it obvious.
