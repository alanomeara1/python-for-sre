"""Outage windows: merge, downtime, availability, concurrent failures."""

from typing import Iterable


def merge_intervals(intervals: Iterable[tuple]) -> list[tuple]:
    merged = []
    for start, end in sorted(intervals):        # merging is only correct on sorted input
        if merged and start <= merged[-1][1]:   # <= so touching windows merge too
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def total_downtime(outages, window_start, window_end):
    # Zero of the right type: 0 for numbers, timedelta(0) for datetimes.
    total = window_start - window_start
    # Merge first, or two alerts for one incident count twice.
    for start, end in merge_intervals(outages):
        start, end = max(start, window_start), min(end, window_end)
        if start < end:
            total += end - start
    return total


def availability(outages, window_start, window_end) -> float:
    # timedelta / timedelta is a float, so this one line covers both types.
    return 1 - total_downtime(outages, window_start, window_end) / (window_end - window_start)


def concurrent_outages(outages_by_service: dict[str, list[tuple]], min_services: int) -> list[tuple]:
    events = []
    for windows in outages_by_service.values():
        for start, end in merge_intervals(windows):  # a service overlapping itself counts once
            if start < end:
                events.append((start, +1))
                events.append((end, -1))

    # At equal timestamps -1 sorts before +1: an end at 10:00 and a start at 10:00 don't overlap.
    events.sort()

    periods = []
    down = 0
    opened_at = None
    for time, delta in events:
        down += delta
        if down >= min_services and opened_at is None:
            opened_at = time
        elif down < min_services and opened_at is not None:
            periods.append((opened_at, time))
            opened_at = None

    return merge_intervals(periods)
