"""Outage windows: merge, downtime, availability, concurrent failures.

Two ideas only: sort-and-walk collapses ONE timeline into continuous windows;
a sweep line over +1/-1 events answers "how many at once?" across MANY timelines.
Full reasoning in EXPLAINED.md.
"""

from typing import Iterable


def merge_intervals(intervals: Iterable[tuple]) -> list[tuple]:
    merged = []
    # Sorted, because the loop only ever compares against merged[-1]. That shortcut is valid
    # only if nothing later can start earlier than something already placed. Unsorted input
    # would need a comparison against every previous window: O(n^2), and this version is
    # simply wrong. sorted() also accepts a generator and returns a list, so streams work free.
    for start, end in sorted(intervals):        # merging is only correct on sorted input
        # <= not <: 10:00-10:30 and 10:30-11:00 touch without overlapping, and that is one
        # continuous outage, not two incidents.
        if merged and start <= merged[-1][1]:   # <= so touching windows merge too
            # max(), because this window may sit ENTIRELY INSIDE the last one ((1,10) then
            # (2,3)); assigning end blindly would shrink it and lose real downtime.
            # Rebuilt rather than mutated: tuples are immutable, so merged[-1][1] = x raises.
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def total_downtime(outages, window_start, window_end):
    # Zero of the right type: 0 for numbers, timedelta(0) for datetimes.
    # Ask the type for its own zero by subtracting a value from itself. Starting at a literal 0
    # works for epoch seconds and then raises TypeError on datetimes (int + timedelta).
    # The rejected alternative, isinstance(window_start, datetime) with two branches, is noisier
    # and still breaks for date or any other type that subtracts sensibly.
    total = window_start - window_start
    # Merge first, or two alerts for one incident count twice.
    # That is the SRE point of the question: double-counting reports an SLO breach that never
    # happened, because availability comes out worse than reality.
    for start, end in merge_intervals(outages):
        # Clip to the reporting window: an outage that began last month must not spend this
        # month's error budget.
        start, end = max(start, window_start), min(end, window_end)
        # After clipping, an outage entirely outside the window comes back inverted (start > end).
        # Without this guard, end - start is NEGATIVE and quietly improves the availability
        # figure -- a bug that survives review because the output still looks plausible.
        if start < end:
            total += end - start
    return total


def availability(outages, window_start, window_end) -> float:
    # timedelta / timedelta is a float, so this one line covers both types.
    # (True division between two timedeltas is defined since Python 3.2.)
    # Written as 1 - downtime/window rather than uptime/window: same arithmetic, but it states
    # the SLO definition directly. Honest gap: a zero-length window raises ZeroDivisionError;
    # nothing tests it and nothing guards it, so say you'd guard it rather than claiming it works.
    return 1 - total_downtime(outages, window_start, window_end) / (window_end - window_start)


def concurrent_outages(outages_by_service: dict[str, list[tuple]], min_services: int) -> list[tuple]:
    # Sweep line: stop thinking about intervals, think about the MOMENTS the count changes.
    # Each window contributes exactly two: +1 when it opens, -1 when it closes. The count is
    # constant between events, so the events are the only places worth looking.
    events = []
    for windows in outages_by_service.values():
        # Merge each service's OWN windows first: a flapping service raises two overlapping
        # alerts, which un-merged would read as two different services being down.
        for start, end in merge_intervals(windows):  # a service overlapping itself counts once
            # A zero-length outage would emit +1 and -1 at the same instant and could tip the
            # count over the threshold for an empty period.
            if start < end:
                events.append((start, +1))
                events.append((end, -1))

    # At equal timestamps -1 sorts before +1: an end at 10:00 and a start at 10:00 don't overlap.
    # This encodes half-open intervals [start, end): an outage "ending at 10:00" is already over.
    # Note it relies on the SIGN of the delta; nothing here says "ends first" out loud. The
    # variant does it properly with named constants. Say the assumption aloud in an interview.
    events.sort()

    periods = []
    down = 0
    # opened_at does two jobs: the "am I inside a qualifying period?" flag, and where it began.
    # Two variables collapsed into one, so they can never disagree.
    opened_at = None
    for time, delta in events:
        down += delta
        if down >= min_services and opened_at is None:
            opened_at = time
        elif down < min_services and opened_at is not None:
            periods.append((opened_at, time))
            opened_at = None

    # Events at one timestamp are applied one at a time, so the count can dip below the
    # threshold and return at the SAME instant, splitting one period in two. Merging rejoins them.
    return merge_intervals(periods)
