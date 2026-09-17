# 10 · Intervals: merge outages, downtime, availability, concurrent failures

**Why this drill:** "Merge overlapping intervals" is a classic coding question, and in SRE
clothing it's how you turn incident timelines into an availability number for an SLO review. The
sweep-line half ("when were two or more services down together?") is the follow-up that separates
people who memorised the trick from people who understand it.

## The task, as an interviewer would say it

> Monitoring gives us outage windows as (start, end) pairs, and they overlap: two alerts can
> fire for the same incident. Merge them. Then tell me the total downtime and availability within a
> reporting window. Last part: given the outages for several services, find the periods where at
> least N services were down at the same time.

```python
outages = [(datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 10, 30)),
           (datetime(2026, 9, 1, 10, 20), datetime(2026, 9, 1, 11, 0)),   # overlaps the first
           (datetime(2026, 9, 1, 11, 0),  datetime(2026, 9, 1, 11, 15))]  # touches the second
merge_intervals(outages)
# -> [(datetime(2026, 9, 1, 10, 0), datetime(2026, 9, 1, 11, 15))]
```

Every function must work on plain numbers (epoch seconds) **and** on `datetime`s.

## Contract (what the tests call)

```python
def merge_intervals(intervals: Iterable[tuple]) -> list[tuple]
    # sorted by start; overlapping OR touching intervals (end == next start) merge
    # input may be unsorted; input order doesn't matter; [] -> []

def total_downtime(outages, window_start, window_end)
    # merged downtime clipped to [window_start, window_end]
    # returns a number for numbers, a timedelta for datetimes

def availability(outages, window_start, window_end) -> float
    # 1 - downtime / window length, e.g. 0.999

def concurrent_outages(outages_by_service: dict[str, list[tuple]], min_services: int) -> list[tuple]
    # periods where >= min_services services were down at once, merged, sorted
    # a service overlapping ITSELF counts once; zero-length outages are ignored
```

## Patterns you are drilling

- `sorted(intervals)`, then walk and compare `start <= merged[-1][1]`
- Clipping: `max(start, window_start)`, `min(end, window_end)`, skip if `start >= end`
- Sweep line: turn intervals into `(time, +1)` / `(time, -1)` events, sort, keep a running count
- Tie-breaking with the sort key: `(time, delta)` puts `-1` before `+1` at the same instant
- `timedelta / timedelta` gives a float, so availability works for datetimes with no special case

## Say this out loud (what the interviewer listens for)

- "Sort first, that's O(n log n). Then one linear pass to merge."
- "I merge before summing, otherwise two alerts for the same incident double-count the downtime
  and make availability look worse than it was."
- "At the same timestamp I process ends before starts, so one outage ending at 10:00 and another
  starting at 10:00 don't count as concurrent."
- "I merge each service's own windows first. A flapping service isn't two services down."
- SLO tie-in: "0.999 over 30 days is about 43 minutes of budget. This is the number I'd put in the
  monthly review, next to how much budget each incident burned."

## Traps

- Forgetting to sort. The merge is only correct on sorted input.
- `start < last_end` instead of `<=`, which leaves touching windows unmerged.
- Starting the sum at `0` for datetimes: `0 + timedelta` raises `TypeError`.
  `window_start - window_start` is a zero of the right type for both.
- Not clipping outages that start before or end after the reporting window.
- Mutating a tuple: build a new `(start, max(end, last_end))`.
