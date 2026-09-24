"""Single-pass, bounded-memory aggregation over an event stream.

Memory is bounded by CARDINALITY (distinct keys, one bucket), never by how many
events go past. Full reasoning in EXPLAINED.md.
"""

import heapq
from collections import Counter
from itertools import groupby
from typing import Iterable, Iterator


def top_k(events: Iterable[dict], k: int, key: str) -> list[tuple[object, int]]:
    counts = Counter()
    for event in events:
        # Missing key = ignore, not KeyError: a heterogeneous event stream is normal.
        if key in event:
            counts[event[key]] += 1
    # Counter keeps first-seen order, and nlargest is stable, so ties come out deterministically.
    # nlargest is O(n log k) against sorted()'s O(n log n), which matters when k is 10 and n is
    # millions. Memory here is O(distinct values): fine for endpoints, dangerous for user IDs on
    # a public API -- at that cardinality, switch to a Count-Min sketch or HyperLogLog.
    return heapq.nlargest(k, counts.items(), key=lambda item: item[1])


def dedupe_consecutive(lines: Iterable[str]) -> Iterator[tuple[str, int]]:
    # groupby groups ADJACENT equal items, which is exactly syslog's "repeated N times".
    # Unlike SQL GROUP BY it does not collect all equal items everywhere -- and that is the
    # requirement, not a limitation.
    for line, run in groupby(lines):
        # Consume `run` immediately: groupby invalidates a group's iterator as soon as it
        # advances, so the count must be taken now and the groups can never be stashed.
        yield line, sum(1 for _ in run)


def window_counts(timestamps: Iterable[float], bucket_seconds: int) -> Iterator[tuple[int, int]]:
    # Only ever one bucket in memory, so this runs on an endless stream. It is the core of
    # every metrics pipeline.
    current_bucket = None
    count = 0
    for ts in timestamps:
        # Floor onto the bucket boundary, and int() so a float timestamp still yields an int key.
        bucket = int(ts // bucket_seconds) * bucket_seconds
        # Raise rather than miscount a bucket that has already been emitted downstream. Real
        # pipelines take late events with a watermark and an allowed-lateness window instead.
        if current_bucket is not None and bucket < current_bucket:
            raise ValueError(f"out-of-order timestamp {ts} (current bucket {current_bucket})")
        if bucket != current_bucket:
            if current_bucket is not None:
                yield current_bucket, count     # bucket is complete: emit now, hold nothing
            current_bucket, count = bucket, 0
        count += 1
    # The final bucket has no later timestamp to close it, so flush it when the input ends.
    if current_bucket is not None:
        yield current_bucket, count
