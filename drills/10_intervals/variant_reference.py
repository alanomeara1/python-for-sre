"""On-call rota checks: coverage gaps and double-bookings.

Gaps are the complement of the merged shifts, found with a cursor. Double-bookings
are a sweep line whose running state is WHO is on call, not how many.
Full reasoning in EXPLAINED.md.
"""

from collections import Counter
from datetime import datetime
from typing import Iterable

Shift = tuple[str, datetime, datetime]

# Named constants instead of the main drill's bare +1/-1: this says "ends before starts at the
# same instant" in words, so a clean 17:00 handover is never reported as an overlap.
START, END = 1, 0   # END sorts first at the same instant: a clean handover isn't an overlap


def coverage_gaps(shifts: Iterable[Shift], period_start: datetime, period_end: datetime) -> list[tuple]:
    gaps = []
    cursor = period_start               # everything before cursor is known to be covered
    # key=lambda s: s[1] because a shift is (person, start, end). A bare sorted() would order
    # these ALPHABETICALLY BY PERSON and silently produce nonsense. The main drill got away with
    # a bare sorted() only because its tuples happened to start with the time.
    for _, start, end in sorted(shifts, key=lambda s: s[1]):
        start, end = max(start, period_start), min(end, period_end)
        if start >= end:
            continue                    # entirely outside the period
        # A shift beginning after the cursor means nobody was on call in between.
        if start > cursor:
            gaps.append((cursor, start))
        cursor = max(cursor, end)       # max: a short shift inside a long one mustn't move us back
    # The tail: the rota can simply stop before the period does, and that is a gap too.
    if cursor < period_end:
        gaps.append((cursor, period_end))
    return gaps


def double_booked(shifts: Iterable[Shift]) -> list[tuple]:
    events = []
    for person, start, end in shifts:
        events.append((start, START, person))
        events.append((end, END, person))
    # Sort on (time, kind) only. Explicit, so the tie-break is a decision rather than a
    # side effect of person names comparing alphabetically.
    events.sort(key=lambda e: (e[0], e[1]))

    on_call = Counter()                 # Counter, not set: one person may have overlapping shifts
    # A set would be wrong here: when the first of someone's two overlapping shifts ends,
    # discard() takes them off call while they are still on. The Counter drops to 1 instead.
    result = []
    previous = None
    for time, kind, person in events:
        # The stretch [previous, time) had whoever was on call before this event.
        # So report it BEFORE applying the current event: the cast during that stretch was set
        # by the earlier events, not this one.
        if previous is not None and time > previous and len(on_call) >= 2:
            people = sorted(on_call)
            # Same cast, no break in between: one continuous overlap, not two. This is what
            # joins someone's back-to-back shifts alongside a colleague into a single stretch.
            if result and result[-1][1] == previous and result[-1][2] == people:
                result[-1] = (result[-1][0], time, people)      # extend the same stretch
            else:
                result.append((previous, time, people))

        if kind == START:
            on_call[person] += 1
        else:
            on_call[person] -= 1
            # Delete at zero so len(on_call) is the number of people actually on call:
            # a Counter keeps keys with a 0 value, which would inflate that count.
            if on_call[person] == 0:
                del on_call[person]
        previous = time
    return result
