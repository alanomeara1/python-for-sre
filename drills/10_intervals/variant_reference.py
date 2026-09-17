"""On-call rota checks: coverage gaps and double-bookings."""

from collections import Counter
from datetime import datetime
from typing import Iterable

Shift = tuple[str, datetime, datetime]

START, END = 1, 0   # END sorts first at the same instant: a clean handover isn't an overlap


def coverage_gaps(shifts: Iterable[Shift], period_start: datetime, period_end: datetime) -> list[tuple]:
    gaps = []
    cursor = period_start               # everything before cursor is known to be covered
    for _, start, end in sorted(shifts, key=lambda s: s[1]):
        start, end = max(start, period_start), min(end, period_end)
        if start >= end:
            continue                    # entirely outside the period
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)       # max: a short shift inside a long one mustn't move us back
    if cursor < period_end:
        gaps.append((cursor, period_end))
    return gaps


def double_booked(shifts: Iterable[Shift]) -> list[tuple]:
    events = []
    for person, start, end in shifts:
        events.append((start, START, person))
        events.append((end, END, person))
    events.sort(key=lambda e: (e[0], e[1]))

    on_call = Counter()                 # Counter, not set: one person may have overlapping shifts
    result = []
    previous = None
    for time, kind, person in events:
        # The stretch [previous, time) had whoever was on call before this event.
        if previous is not None and time > previous and len(on_call) >= 2:
            people = sorted(on_call)
            if result and result[-1][1] == previous and result[-1][2] == people:
                result[-1] = (result[-1][0], time, people)      # extend the same stretch
            else:
                result.append((previous, time, people))

        if kind == START:
            on_call[person] += 1
        else:
            on_call[person] -= 1
            if on_call[person] == 0:
                del on_call[person]
        previous = time
    return result
