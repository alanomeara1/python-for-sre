# 10 · Variant: on-call schedule gaps and double-bookings

Same patterns as the main drill (sort-and-walk, clipping, sweep line), different problem. As an
SRE Manager you *own* this schedule, so expect it as a follow-up.

## The task

> Here's next week's on-call rota as (person, shift start, shift end). Show me every period in the
> coverage window where nobody is on call. Then show me where two or more people are on at once,
> which is either a handover overlap or somebody's mistake.

```python
shifts = [
    ("aoife",  datetime(2026, 9, 21, 9),  datetime(2026, 9, 21, 17)),
    ("bryan",  datetime(2026, 9, 21, 16), datetime(2026, 9, 22, 0)),
    ("ciara",  datetime(2026, 9, 22, 2),  datetime(2026, 9, 22, 9)),
]
coverage_gaps(shifts, datetime(2026, 9, 21, 9), datetime(2026, 9, 22, 9))
# -> [(datetime(2026, 9, 22, 0), datetime(2026, 9, 22, 2))]
double_booked(shifts)
# -> [(datetime(2026, 9, 21, 16), datetime(2026, 9, 21, 17), ["aoife", "bryan"])]
```

## Contract

```python
def coverage_gaps(shifts: Iterable[tuple[str, datetime, datetime]],
                  period_start: datetime, period_end: datetime) -> list[tuple[datetime, datetime]]
    # uncovered stretches inside [period_start, period_end], sorted.
    # Shifts outside the period, or partly outside, are clipped. No shifts -> the whole period.

def double_booked(shifts: Iterable[tuple[str, datetime, datetime]]) -> list[tuple[datetime, datetime, list[str]]]
    # stretches where >= 2 DIFFERENT people are on call, with those people sorted by name.
    # Back-to-back shifts (end == next start) are not a double-booking.
    # Adjacent stretches with the same people are joined into one.
    # One person with two overlapping shifts is still one person.
```

Hint: the gap walk is "merge, then keep a cursor". The double-booking is a sweep line where the
running state is *who* is on (a `Counter` of people), not just how many.

## Say this out loud

- "Gaps are the complement of the merged shifts inside the period, so I walk a cursor from
  period_start and emit a gap whenever the next shift starts after it."
- "For overlaps I sweep over start and end events. At equal times, ends go first, so a clean
  handover at 17:00 isn't flagged."
- "I track people in a Counter rather than a set. If someone has two overlapping shifts and one ends,
  a set would wrongly take them off call."
- "I'd run this in CI against the rota file, so a gap fails the PR instead of paging nobody at 1am."
