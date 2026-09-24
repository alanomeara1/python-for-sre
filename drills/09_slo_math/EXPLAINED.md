# 09 · Explained: how and why, line by line

Read this in the Study step, and come back to it whenever you're stuck. `reference.py` shows you
*what* to write. This file is *why* it's written that way, so you can rebuild it from scratch
instead of fishing for a memory.

For a manager role this is the drill where the code is the easy part and the conversation is the
interview. Understand the four numbers below and you can derive every function here.

---

## The four numbers, in one paragraph

An **SLO** of 99.9% says 99.9% of requests should succeed. The **error budget** is what's left:
`1 - 0.999` = 0.1% of requests may fail over the SLO period, usually 30 days. The **burn rate** is
how fast you're spending it: observed error rate ÷ error budget. A burn rate of 1 spends the
entire budget exactly over the period; a burn rate of 14.4 spends 2% of a 30-day budget in one
hour, because `14.4 × 1h / 720h = 0.02`. **Multiwindow alerting** pages only when a long window
*and* a short window are both burning fast, so you page on significant, ongoing problems and not
on blips.

**Memory hook: budget = 1 − SLO. Burn = error rate ÷ budget. Page when long AND short both burn.**

Everything in `reference.py` is one of those four sentences turned into three lines of Python.

---

## The mental model

```
percentile(values, p)                  raw latencies    → the number on the dashboard
availability(good, total)              raw counts       → the number in the SLA
error_budget_remaining(slo, good, ...) counts + target  → how much room is left
burn_rate(slo, error_rate)             rate + target    → how fast we're spending it
should_page(...)                       two burn rates   → whether to wake someone
```

Small functions building into bigger ones: `should_page` calls `burn_rate` twice and contains no
arithmetic of its own. That's deliberate. If the definition of burn rate changes, one function
changes.

---

## Chunk 1: `percentile`

```python
def percentile(values: Iterable[float], p: float) -> float:
    if not 0 <= p <= 100:
        raise ValueError(f"percentile must be in [0, 100], got {p}")
    ordered = sorted(values)              # sort first: works for generators too
    if not ordered:
        raise ValueError("percentile of empty data")

    # Nearest-rank. Multiply before dividing: 7 / 100 * 100 == 7.000000000000001.
    rank = max(1, math.ceil(p * len(ordered) / 100))
    return float(ordered[rank - 1])
```

**Why validate `p` before touching the data:** it's the cheap check, and it's a caller bug rather
than a data condition. Note the chained comparison `0 <= p <= 100` reads as the maths does.

**Why `sorted(values)` before the emptiness check:** `if not values` is *always false* for a
generator, because a generator object is truthy whether or not it will yield anything. Sorting
materialises it into a list, and then `if not ordered` is meaningful. There's a test that passes
`iter([])` for exactly this. It's also why the parameter is typed `Iterable`: sorting accepts
anything you can loop over.

**Why nearest-rank rather than interpolation:** nearest-rank returns **a latency somebody actually
experienced**. Interpolating between two samples (numpy's default, and the `statistics.quantiles`
default) can report 247ms when no request ever took 247ms. For SLO reporting, the observed value
is easier to defend and easier to explain to a non-engineer. Either method is acceptable in an
interview; not knowing which one you used is not. Say which and why.

**Why `p * len(ordered) / 100` and not `p / 100 * len(ordered)`:** floating point. `7 / 100` isn't
exactly 0.07, and `7 / 100 * 100` evaluates to `7.000000000000001`, which `math.ceil` rounds up to
8. You'd silently return the 8th smallest value as p7. Multiplying first keeps the intermediate
exact for the sizes that matter here. The test `test_percentile_no_float_rank_error` pins this
with 100 values at p7 and 1000 values at p99.9.

**Why `max(1, ...)`:** at `p=0` the rank is 0, and `ordered[-1]` would return the *largest* value,
the exact opposite of what p0 means. Clamping to rank 1 makes p0 the minimum.

**Why `rank - 1`:** ranks are 1-based (rank 1 is the smallest), Python indices are 0-based. This
off-by-one is the other common slip.

**Why `float(...)`:** integer inputs would otherwise return an int, and a function typed
`-> float` should return one. Small, but it keeps callers from being surprised by `50` where they
expected `50.0`.

**Rebuild it from first principles:** "p99 latency" means the value below which 99% of requests
fall. Sort them, take the position `p%` of the way along (rounding up so you never understate),
convert to a 0-based index.

**The thing to volunteer:** you cannot average percentiles. The p99 of two hosts is not the
average of their p99s. You need the underlying distribution, which is why Prometheus computes
`histogram_quantile` over summed buckets rather than averaging a pre-computed quantile.

---

## Chunk 2: `availability`

```python
def availability(good: int, total: int) -> float:
    return good / total if total else 1.0
```

**Why 1.0 for no requests:** the same divide-by-zero guard as drill 01, but the *choice of default*
is a judgement, not a formula. Zero requests means nothing failed, so reporting 100% keeps a quiet
service from looking like an outage on the dashboard. The counter-argument (a service receiving no
traffic may itself be the incident) is real: that's what a separate "no data" alert is for. Be
ready to defend the choice either way rather than presenting it as obvious.

---

## Chunk 3: `error_budget_remaining`

```python
def error_budget_remaining(slo: float, good: int, total: int) -> float:
    if not 0 < slo < 1:
        raise ValueError(f"SLO must be between 0 and 1 exclusive, got {slo}")
    if total == 0:
        return 1.0

    budget = 1 - slo                      # fraction of requests allowed to fail
    error_rate = (total - good) / total
    return 1 - error_rate / budget        # negative means overspent
```

**Why reject `slo = 1.0`:** a 100% SLO has a zero error budget, so `error_rate / budget` divides by
zero. It's also nonsense operationally: every deploy, every node restart, every network blip is a
violation, and no team can ship. Raising forces the conversation rather than returning `inf`.

**Why reject `slo = 99.9`:** percent instead of fraction is the most likely caller mistake, and it
would otherwise produce a wildly wrong negative budget that looks plausible on a dashboard. The
exclusive bounds catch it for free. There's a test for it.

**Why the result is a *fraction of the budget* rather than a count of requests:** "you have 43% of
your error budget left" is the sentence the error budget policy is written in, and it's
comparable across services of wildly different traffic. Returning "4,300 failures remaining" ties
the number to one service's volume.

**Why negative is allowed through:** overspending is normal, and the amount matters. `-1.0` means
you burned twice the budget. Clamping it to 0 would throw away exactly the information that
triggers a feature freeze.

**Reading the formula:** `error_rate / budget` is "what fraction of the allowance have we used",
which is the burn rate. Subtract from 1 for what's left. If you remember `burn_rate`, you can
derive this line rather than memorising it.

---

## Chunk 4: `burn_rate` and `should_page`

```python
def burn_rate(slo: float, error_rate: float) -> float:
    # 1.0 spends the budget exactly over the SLO period; 14.4 spends 2% of 30 days in 1h.
    return error_rate / (1 - slo)
```

One line, and the whole point is the comment. Be able to derive 14.4 on a whiteboard:
30 days is 720 hours, 2% of the budget in 1 hour means `x × (1/720) = 0.02`, so `x = 14.4`.

Honest caveat: unlike `error_budget_remaining`, this function doesn't validate `slo`, so
`burn_rate(1.0, ...)` raises `ZeroDivisionError` rather than a clear `ValueError`. In production
code you'd validate here too; the drill keeps it to one line because that's how it appears in
almost every real codebase.

```python
def should_page(slo: float, short_window_error_rate: float,
                long_window_error_rate: float, threshold: float = 14.4) -> bool:
    # Long window: it's significant. Short window: it's still happening.
    return (burn_rate(slo, long_window_error_rate) >= threshold
            and burn_rate(slo, short_window_error_rate) >= threshold)
```

**Why `and`, never `or`:** each window alone is a bad alert.

- **Long window alone** (say 1 hour) keeps paging for an hour after you've fixed the problem,
  because the hour of bad data is still in the window. Alerts that fire after the fix train people
  to ignore alerts.
- **Short window alone** (say 5 minutes) pages on every transient blip, most of which recover
  before anyone opens a laptop.
- **Both together**: the long window proves it's significant, the short window proves it's *still
  happening*. And because the short window empties quickly, the alert resolves soon after the fix.

Swapping `and` for `or` is the classic bug here, and it's tested from both directions: long burning
with short recovered, and short spiking with long fine. Both must be `False`.

**Why `threshold` is a parameter with a default:** the SRE workbook defines a ladder, not one
number. 14.4 over 1h/5m pages; 6 over 6h/30m pages; 1 over 3d/6h raises a ticket instead. A
parameter lets one function serve all three tiers.

**Why keyword arguments matter at the call site:** `should_page(0.999, 0.02, 0.015)` gives no clue
which window is which, and swapping them inverts the logic in a way no test you write by hand will
catch. The tests call it with `short_window_error_rate=` and `long_window_error_rate=` spelled out.

---

## When a test fails

| Failing test | What it's telling you |
|---|---|
| `test_percentile_nearest_rank` | the `rank - 1` off-by-one, or `max(1, ...)` missing so p0 returns the largest value |
| `test_percentile_no_float_rank_error` | you wrote `p / 100 * n` and float error pushed the rank up one |
| `test_percentile_accepts_generator` | you indexed or measured `values` before sorting |
| `test_percentile_invalid_input` | `if not values` on a generator (always false), or no range check on `p` |
| `test_availability` | no guard for `total == 0` |
| `test_error_budget_remaining` | dividing by `total` rather than by the budget, or clamping negatives to 0 |
| `test_error_budget_rejects_impossible_slo` | bounds not exclusive, so `slo=1.0` or `slo=99.9` slips through |
| `test_burn_rate` | dividing by `slo` instead of by `1 - slo` |
| `test_should_page_needs_both_windows` | `or` instead of `and`, or the two windows swapped |
| `test_should_page_custom_threshold` | hardcoded 14.4 instead of using the parameter |

Floats: `1 - 0.999` is `0.0010000000000000009`, which is why the tests use `approx` and avoid
sitting exactly on a boundary. Do the same in your own assertions.

---

## The variant: what actually changes

Incident metrics from a CSV export is the same job (turn raw operational data into the numbers
leadership asks for) with `csv` and `datetime` instead of arithmetic. Five ideas:

1. **Parse once into typed records, then compute.** `load_incidents` converts every timestamp to a
   `datetime` up front, and every metric works on those records. Re-parsing strings inside each
   metric is slower and scatters the format knowledge across the file. Same "convert at the edge"
   principle as `parse_line` in drill 01.

2. **`csv.DictReader(io.StringIO(text))`.** `DictReader` uses the header row for keys, so
   `row["severity"]` reads clearly and survives a column being inserted. Wrapping the text in
   `StringIO` makes it behave like an open file, so the identical code works on a real file handle,
   and the tests need no filesystem. (`datetime.fromisoformat` accepting a trailing `Z` needs
   Python 3.11+, which this repo has.)

3. **Average only what exists, and count the rest separately.** MTTR is the mean over incidents
   that *are resolved*; MTTA over those that *have* an ack. Treating an unresolved incident as
   zero duration would make MTTR look **better** the worse things get, which is the kind of metric
   bug that survives for years because nobody wants to question good news. Open incidents get
   their own count instead.

4. **`None`, not `0`, when there's nothing to average.** A severity with no resolved incidents has
   no MTTR. Reporting `0.0` would say "we fix SEV3s instantly". `None` forces the dashboard to
   render "n/a" and forces the reader to notice.

5. **`now` makes open incidents measurable, and its absence is meaningful.** In `worst_incidents`,
   an unresolved incident has no end time; passing `now` says "measure it up to here", and leaving
   it out skips them. That's an explicit choice at the call site rather than a hidden default.
   The sort key `(-duration, id)` is the two-key pattern from drill 01: longest first, ties broken
   deterministically by id.

The judgement to voice, and it's the manager-level point: **MTTR is a mean, so one three-day
incident dominates the quarter.** Show the median and the worst-N alongside it. And be wary of
MTTR as a team target, because the easiest way to improve it is to close incidents early.
